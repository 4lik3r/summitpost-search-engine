import html
import os
import re
import sys

from extractor import clean

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
# the dump stays packed (.bz2), spark reads it directly and splits it between the cores
DUMP = os.path.join(DATA, "wiki", "enwiki-20261001-pages-articles.xml.bz2")
OUT_MOUNTAINS = os.path.join(DATA, "spark", "wiki_mountains")
OUT_REDIRECTS = os.path.join(DATA, "spark", "wiki_redirects")

MOUNTAIN_COLUMNS = ["wiki_title", "elevation_m", "prominence_m", "isolation_km", "first_ascent", "listing", "range",
                    "type", "last_eruption", "easiest_route", "other_name", "etymology", "wiki_lat", "wiki_lon", "lead"]

# <title>Matterhorn</title>
TITLE_RE = re.compile(r"<title>(.*?)</title>")
# <ns>0</ns>  -> 0 = normal article (not a talk page, category, template, ...)
NS_RE = re.compile(r"<ns>(\d+)</ns>")
# <redirect title="Annapurna" />  -> the page is only a redirect to another article
REDIRECT_RE = re.compile(r'<redirect title="([^"]*)"')
# <text bytes="..." xml:space="preserve">'''Matterhorn''' is a mountain ...</text>
TEXT_RE = re.compile(r"<text[^>]*>(.*?)</text>", re.S)
# {{Infobox mountain  or  {{Infobox volcano   -> the article is about a mountain
INFOBOX_RE = re.compile(r"\{\{\s*infobox[ _]+(?:mountain|volcano)", re.I)
# | elevation_m = 4478   -> one field of the infobox
FIELD_RE = re.compile(r"^\s*\|\s*([\w ]+?)\s*=(.*)$")

# wiki markup that we throw away
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
REF_RE = re.compile(r"<ref[^>/]*/>|<ref[^>]*>.*?</ref>", re.S | re.I)
TAG_RE = re.compile(r"<[^>]+>")
FILE_RE = re.compile(r"\[\[(?:File|Image):[^\[\]]*(?:\[\[[^\[\]]*\]\][^\[\]]*)*\]\]", re.I)
# [[Pennine Alps]] -> Pennine Alps,  [[Zermatt|the village]] -> the village
LINK_RE = re.compile(r"\[\[(?:[^\[\]|]*\|)?([^\[\]]*)\]\]")
# [https://example.com some text] -> some text
EXTERNAL_LINK_RE = re.compile(r"\[https?://[^\s\]]+\s*([^\]]*)\]")
INNER_TEMPLATE_RE = re.compile(r"\{\{([^{}]*)\}\}")
TABLE_RE = re.compile(r"\{\|.*?\|\}", re.S)
BOLD_RE = re.compile(r"'{2,}")
# what stays after removing pronunciations: "Ben Nevis ( ; Beinn Nibheis, )" -> "Ben Nevis (Beinn Nibheis)"
EMPTY_PARENS_RE = re.compile(r"\(\s*[,;]*\s*\)")
PARENS_START_RE = re.compile(r"\(\s*(?:[,;]\s*)+")
PARENS_END_RE = re.compile(r"(?:\s*[,;])+\s*\)")
SPACE_BEFORE_RE = re.compile(r"\s+([,;.)])")
SEPARATORS_RE = re.compile(r"(?:\s*[;,]\s*){2,}")
NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")

# templates where we keep the last argument: {{nowrap|text}} -> text, {{lang|it|Monte Cervino}} -> Monte Cervino
KEEP_LAST = {"nowrap", "lang", "transl", "transliteration", "small", "abbr", "nobr", "langx", "native name", "ill"}
# list templates, we keep all items: {{Plainlist| *14 July 1865 by *Edward Whymper}} -> 14 July 1865 by, Edward Whymper
LISTS = {"plainlist", "unbulleted list", "ubl", "flatlist", "hlist", "bulleted list", "ublist"}
FEET_IN_METER = 3.28084


# {{name|arg|arg}} -> plain text, only the templates we know, the rest is removed
def template_text(match):
    parts = [p.strip() for p in match.group(1).split("|")]
    name = parts[0].lower().strip()
    args = [p for p in parts[1:] if "=" not in p]  # named arguments like "abbr=on" are only formatting
    if name in ("convert", "cvt") and args:
        return " ".join(args[:2])                     # {{convert|4478|m|ft}} -> 4478 m
    if name in ("start date", "date", "start date and age") and args:
        return "-".join(args[:3])                     # {{start date|1865|7|14}} -> 1865-7-14
    if name in KEEP_LAST and args:
        return args[-1]
    if name in LISTS and args:
        return ", ".join(re.sub(r"\s*\*\s*", ", ", a).strip(" ,") for a in args)
    return " "


# wiki markup -> plain ASCII text on one line
def wiki_to_text(text):
    text = COMMENT_RE.sub(" ", text)
    text = REF_RE.sub(" ", text)
    text = FILE_RE.sub(" ", text)
    text = TABLE_RE.sub(" ", text)
    # links first, their "|" ([[Charles Hudson (climber)|Charles Hudson]]) would break the template arguments
    text = LINK_RE.sub(r"\1", text)
    # templates can be inside templates, so we replace the inner ones first, until there are none
    while True:
        new = INNER_TEMPLATE_RE.sub(template_text, text)
        if new == text:
            break
        text = new
    text = text.replace("<br>", ", ").replace("<br />", ", ").replace("<br/>", ", ")
    text = LINK_RE.sub(r"\1", text)  # links that were inside a template
    text = EXTERNAL_LINK_RE.sub(r"\1", text)
    text = text.replace("[[", "").replace("]]", "")  # broken links that had a template inside
    text = TAG_RE.sub(" ", text)
    text = BOLD_RE.sub("", text)
    text = clean(text)
    text = EMPTY_PARENS_RE.sub("", text)
    text = PARENS_START_RE.sub("(", text)
    text = PARENS_END_RE.sub(")", text)
    text = SEPARATORS_RE.sub("; ", text)
    text = SPACE_BEFORE_RE.sub(r"\1", text)
    return re.sub(r"\s+", " ", text).strip(" ;,")


# the infobox ends where its {{ is closed, templates inside it have their own {{ }}
def infobox_text(text):
    start = INFOBOX_RE.search(text).start()
    depth = 0
    i = start
    while i < len(text) - 1:
        if text[i:i + 2] == "{{":
            depth += 1
            i += 2
        elif text[i:i + 2] == "}}":
            depth -= 1
            i += 2
            if depth == 0:
                return text[start:i], i
        else:
            i += 1
    return text[start:], len(text)


# infobox -> {field: raw value}, a value can continue on the next lines
def infobox_fields(box):
    fields = {}
    field = None
    for line in box[:-2].split("\n")[1:]:  # [:-2] = without the closing }} of the infobox
        found = FIELD_RE.match(line)
        if found:
            field = found.group(1).strip().lower().replace(" ", "_")
            fields[field] = found.group(2).strip()
        elif field:
            fields[field] += " " + line.strip()
    return fields


# elevation_m = 4478  or  elevation_ft = 8363  or  elevation = {{convert|14692|ft|m}}  -> meters as text
def meters(fields, name):
    value = fields.get(name + "_m", "")
    feet = NUMBER_RE.search(fields.get(name + "_ft", ""))
    if not NUMBER_RE.search(value) and feet:
        return str(round(float(feet.group().replace(",", "")) / FEET_IN_METER))
    if not NUMBER_RE.search(value):
        found = re.search(r"\{\{\s*(?:convert|cvt)\s*\|\s*([\d,.]+)\s*\|\s*(m|ft)\b", fields.get(name, ""), re.I)
        if not found:
            found = re.search(r"([\d,.]+)\s*(m|ft)\b", fields.get(name, ""))
        if not found:
            return ""
        number = float(found.group(1).replace(",", "") or 0)
        return str(round(number / FEET_IN_METER if found.group(2).lower() == "ft" else number))
    return NUMBER_RE.search(value).group().replace(",", "")


# {{coord|45|58|35|N|7|39|31|E|...}}  or  {{coord|45.976|7.658}}  -> (lat, lon) as decimal numbers
def coordinates(box):
    found = re.search(r"\{\{\s*coord\s*\|([^{}]*)\}\}", box, re.I)
    if not found:
        return "", ""
    args = [a.strip() for a in found.group(1).split("|") if "=" not in a and ":" not in a]
    try:
        if any(a.upper() in ("N", "S") for a in args):
            ns = next(i for i, a in enumerate(args) if a.upper() in ("N", "S"))
            ew = next(i for i, a in enumerate(args) if a.upper() in ("E", "W"))
            lat = sum(float(v) / 60 ** k for k, v in enumerate(args[:ns]))
            lon = sum(float(v) / 60 ** k for k, v in enumerate(args[ns + 1:ew]))
            lat = -lat if args[ns].upper() == "S" else lat
            lon = -lon if args[ew].upper() == "W" else lon
        else:
            lat, lon = float(args[0]), float(args[1])
    except (StopIteration, ValueError, IndexError):
        return "", ""
    return f"{lat:.5f}", f"{lon:.5f}"


# one <page> of the dump -> ("redirect", title, target) or ("mountain", [values]) or None
def parse_page(page):
    title = TITLE_RE.search(page)
    ns = NS_RE.search(page)
    if not title or not ns or ns.group(1) != "0":
        return None
    title = html.unescape(title.group(1))
    redirect = REDIRECT_RE.search(page)
    if redirect:
        return ("redirect", title, html.unescape(redirect.group(1)))
    text = TEXT_RE.search(page)
    if not text or not INFOBOX_RE.search(text.group(1)):
        return None  # not a mountain, most of the pages end here

    text = html.unescape(text.group(1))  # in the dump &lt;ref&gt; is written like that
    box, end = infobox_text(text)
    fields = infobox_fields(box)
    lat, lon = coordinates(box)
    # lead = the text after the infobox until the first chapter ("== History ==")
    lead = text[end:].split("\n==")[0]
    other_name = "; ".join(v for v in (fields.get("other_name", ""), fields.get("native_name", "")) if v)

    values = {
        "wiki_title": title,
        "elevation_m": meters(fields, "elevation"),
        "prominence_m": meters(fields, "prominence"),
        "isolation_km": (NUMBER_RE.search(fields.get("isolation_km", "")) or [""])[0].replace(",", ""),
        "first_ascent": wiki_to_text(fields.get("first_ascent", "")),
        "listing": wiki_to_text(fields.get("listing", "")),
        "range": wiki_to_text(fields.get("range", "") or fields.get("parent_range", "")),
        "type": wiki_to_text(fields.get("type", "") or fields.get("mountain_type", "")),
        "last_eruption": wiki_to_text(fields.get("last_eruption", "")),
        "easiest_route": wiki_to_text(fields.get("easiest_route", "")),
        "other_name": wiki_to_text(other_name),
        "etymology": wiki_to_text(fields.get("etymology", "")),
        "wiki_lat": lat,
        "wiki_lon": lon,
        "lead": wiki_to_text(lead),
    }
    return ("mountain", [values[c] for c in MOUNTAIN_COLUMNS])


def write_tsv(df, path):
    (df.repartition(1).write.mode("overwrite")
       .option("sep", "\t").option("header", True).option("quote", "").option("escape", "")
       .option("emptyValue", "")  # empty value = nothing, spark writes "" by default
       .csv(path))


def main():
    from pyspark import StorageLevel
    from pyspark.sql import SparkSession

    dump = sys.argv[1] if len(sys.argv) > 1 else DUMP
    spark = SparkSession.builder.appName("wiki-mountains").getOrCreate()

    # lineSep="</page>" -> one record = one whole <page>...</page> of the dump
    pages = spark.read.option("lineSep", "</page>").text(dump).rdd.map(lambda row: row.value)
    # we keep the parsed pages (memory, or disk when the memory is full), so the dump is read only once
    parsed = pages.map(parse_page).filter(lambda x: x is not None).persist(StorageLevel.MEMORY_AND_DISK)

    redirects = parsed.filter(lambda x: x[0] == "redirect").map(lambda x: [x[1], x[2]])
    mountains = parsed.filter(lambda x: x[0] == "mountain").map(lambda x: x[1])

    write_tsv(spark.createDataFrame(redirects, ["title", "target"]), OUT_REDIRECTS)
    write_tsv(spark.createDataFrame(mountains, MOUNTAIN_COLUMNS), OUT_MOUNTAINS)

    print(f"Done, {mountains.count()} mountain articles, {redirects.count()} redirects")
    spark.stop()


if __name__ == "__main__":
    main()
