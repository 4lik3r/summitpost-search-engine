import math
import os
import re

from pyspark.sql import SparkSession

from extractor import COLUMNS, clean

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
SUMMITPOST = os.path.join(DATA, "spark", "summitpost")
WIKI_MOUNTAINS = os.path.join(DATA, "spark", "wiki_mountains")
WIKI_REDIRECTS = os.path.join(DATA, "spark", "wiki_redirects")
OUT = os.path.join(DATA, "spark", "joined")
STATS = os.path.join(DATA, "spark", "join_stats.txt")

WIKI_COLUMNS = ["wiki_title", "elevation_m", "prominence_m", "isolation_km", "first_ascent", "listing", "range",
                "type", "last_eruption", "easiest_route", "other_name", "etymology", "wiki_lat", "wiki_lon", "lead"]
MAX_KM = 20         # the same mountain on summitpost and wiki cant be further apart than this
MAX_ELEVATION = 300  # the elevations on summitpost and wiki cant differ more than this (m)

# "Mont Blanc/Monte Bianco", "Matterhorn - Monte Cervino", "Wolowiec (Volovec)" -> the names inside
PARTS_RE = re.compile(r"/| - |\(|\)|,")
# "Wheeler Peak (Nevada)" -> "Wheeler Peak"
QUALIFIER_RE = re.compile(r"\s*\([^()]*\)$")


# short forms that are written both ways: "Mount St. Helens" (wiki) and "Mount Saint Helens" (summitpost)
SHORT_FORMS = {"st": "saint", "mt": "mount", "mtn": "mountain"}


# name -> join key: plain ASCII, lowercase, only letters and digits ("Kriváň" and "Krivan" -> "krivan")
def name_key(name):
    words = re.sub(r"[^a-z0-9]+", " ", clean(name or "").lower()).split()
    return " ".join(SHORT_FORMS.get(word, word) for word in words)


# our mountain -> (key, (id, how)): the whole name and every part of it
def our_keys(row):
    keys = [(name_key(row["name"]), (row["id"], "exact"))]
    for part in PARTS_RE.split(row["name"] or ""):
        if len(name_key(part)) >= 3 and name_key(part) != keys[0][0]:
            keys.append((name_key(part), (row["id"], "part")))
    return keys


# wiki article -> (key, (title, how)): the title and the title without "(...)"
def wiki_keys(title):
    keys = [(name_key(title), (title, "exact"))]
    base = QUALIFIER_RE.sub("", title)
    if base != title:
        keys.append((name_key(base), (title, "qualifier")))
    return keys


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# distance between two points on earth in km (haversine)
def km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(math.radians, (lat1, lon1, lat2, lon2))
    a = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


# all wiki candidates of one of our mountains -> the right one or None
#   both have coordinates -> the closest one, if it is max MAX_KM away
#   no coordinates        -> only if there is just one candidate
#                            (5 different "Bald Mountain"s were joined to Bald Mountain (Pennsylvania) only by elevation)
#   and always: if both have an elevation, max MAX_ELEVATION m difference
#   (without this a peak was joined to its range: Granite Peak, Snake Range 3419 m -> Snake Range 3982 m)
def pick(our, candidates):
    best = None
    for wiki, how in candidates:
        lat, lon = number(our["lat"]), number(our["lon"])
        wlat, wlon = number(wiki["wiki_lat"]), number(wiki["wiki_lon"])
        elevation, welevation = number(our["elevation_m"]), number(wiki["elevation_m"])
        same_elevation = None in (elevation, welevation) or abs(elevation - welevation) <= MAX_ELEVATION
        if None not in (lat, lon, wlat, wlon):
            distance = km(lat, lon, wlat, wlon)
            ok = distance <= MAX_KM and same_elevation
        else:
            distance = 0
            ok = len(candidates) == 1 and same_elevation
        if ok and (best is None or distance < best[0]):
            best = (distance, wiki, how)
    return best


def write_tsv(df, path):
    (df.repartition(1).write.mode("overwrite")
       .option("sep", "\t").option("header", True).option("quote", "").option("escape", "")
       .option("emptyValue", "").option("nullValue", "")
       .csv(path))


def read_tsv(spark, path):
    return spark.read.option("sep", "\t").option("header", True).option("quote", "").csv(path).fillna("")


def main():
    spark = SparkSession.builder.appName("summitpost-wiki-join").getOrCreate()
    ours = read_tsv(spark, SUMMITPOST)
    wiki = read_tsv(spark, WIKI_MOUNTAINS)
    redirects = read_tsv(spark, WIKI_REDIRECTS)

    # wiki side keys: article titles + redirects that point to a mountain article
    wiki_titles = set(wiki.select("wiki_title").rdd.map(lambda r: r[0]).collect())
    titles = spark.sparkContext.broadcast(wiki_titles)
    wiki_side = wiki.rdd.flatMap(lambda r: wiki_keys(r["wiki_title"]))
    redirect_side = (redirects.rdd
                     .map(lambda r: (r["title"], r["target"].split("#")[0]))   # "Target#Section" -> "Target"
                     .filter(lambda r: r[1] in titles.value)
                     .map(lambda r: (name_key(r[0]), (r[1], "redirect"))))
    all_wiki_keys = wiki_side.union(redirect_side).distinct()

    # join on the name key -> candidates for every one of our mountains
    candidates = (ours.rdd.flatMap(our_keys).join(all_wiki_keys)
                  .map(lambda kv: (kv[1][1][0], (kv[1][0][0], "part" if kv[1][0][1] == "part" else kv[1][1][1])))
                  .distinct())                                      # (wiki_title, (our_id, how))

    # add the wiki rows and our rows to the candidates, then pick the best one per mountain
    wiki_rows = wiki.rdd.map(lambda r: (r["wiki_title"], r.asDict()))
    our_rows = ours.rdd.map(lambda r: (r["id"], r.asDict()))
    with_wiki = candidates.join(wiki_rows).map(lambda kv: (kv[1][0][0], (kv[1][1], kv[1][0][1])))  # (our_id, (wiki, how))
    picked = (with_wiki.groupByKey().join(our_rows)
              .map(lambda kv: (kv[0], pick(kv[1][1], list(kv[1][0]))))
              .filter(lambda kv: kv[1] is not None)
              .map(lambda kv: (kv[0], kv[1][1], kv[1][2])))                 # (our_id, wiki row, how)

    # left join: every summitpost mountain stays, the wiki columns are empty when we didnt find it
    matched = picked.map(lambda x: (x[0], [x[1][c] for c in WIKI_COLUMNS] + [x[2]]))
    empty = [""] * (len(WIKI_COLUMNS) + 1)
    joined = (our_rows.leftOuterJoin(matched)
              .map(lambda kv: [kv[1][0][c] for c in COLUMNS] + (kv[1][1] or empty)))
    # wiki elevation_m -> wiki_elevation_m, otherwise the output has two elevation_m columns
    out_columns = COLUMNS + ["wiki_" + c if c == "elevation_m" else c for c in WIKI_COLUMNS] + ["match_type"]
    result = spark.createDataFrame(joined, out_columns).cache()
    write_tsv(result, OUT)

    # statistics for the wiki page
    matched_rows = result.filter(result.wiki_title != "")
    lines = [
        f"SummitPost mountains: {ours.count()}",
        f"Wiki mountain articles in the dump: {wiki.count()}",
        f"Redirects to mountain articles: {redirect_side.count()}",
        f"SummitPost mountains joined with wiki: {matched_rows.count()}",
        f"Unique wiki pages joined: {matched_rows.select('wiki_title').distinct().count()}",
    ]
    for row in matched_rows.groupBy("match_type").count().orderBy("count", ascending=False).collect():
        lines.append(f"  match_type {row['match_type']}: {row['count']}")
    print("\n".join(lines))
    with open(STATS, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    spark.stop()


if __name__ == "__main__":
    main()
