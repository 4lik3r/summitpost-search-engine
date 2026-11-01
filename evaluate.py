import os
import time

import lucene

import lucene_search
import search

OUT = os.path.join(search.DATA, "evaluation.txt")
TIMING_RUNS = 10  # every query is run this many times for the time measurement, we take the average


# relevant (correct) mountains for every query, from known facts, not from our results
# a rule is used where the list is long: fn(row of extracted_data) -> True/False
def colorado_fourteener(row):
    return "Colorado" in row["region"] and int(row["elevation_m"] or 0) >= 4267  # 14 000 ft


def high_tatras(row):
    return row["parent"] == "High Tatras / Vysoke Tatry" or row["region"] in ("High Tatra", "HIGH TATRAS", "Vysoke Tatry")


QUERIES = [
    # the 14 eight-thousanders
    ("eight thousander", {150230, 150257, 150283, 150575, 150293, 150294, 150777, 150687, 150276, 150258,
                          152035, 151330, 153264, 150807}),
    # seven summits (both versions: Kosciuszko and Carstensz Pyramid)
    ('"seven summits"', {150230, 150197, 150199, 150202, 150255, 830860, 150910, 150304}),
    # colorado peaks over 14 000 ft
    ("colorado fourteener", colorado_fourteener),
    # peaks in the high tatras
    ('"high tatras"', high_tatras),
    # one correct page
    ("matterhorn", {150235}),      # Matterhorn - Monte Cervino
    ("krivan", {154957}),          # Krivan
    ("annapurna", {150258}),       # Annapurna I
    ('"mount whitney"', {150227}),  # Mount Whitney
]

# top 5 from google (query + site:summitpost.org) and from the summitpost.org search bar (after enter)
# searched by hand, results as summitpost ids, None = not a mountain page (page type in the comment)
GOOGLE = {
    "eight thousander": [None, None, None, None, None],  # photo, photo, photo, photo, fact sheet
    '"seven summits"': [None, None, None, None, None],   # list, list, list, route, photo
    "colorado fourteener": [None, None, None, None, None],  # list, album, list, more list, climbers log
    '"high tatras"': [None, None, None, None, None],     # area/range, photo, images, photo, area/range
    "matterhorn": [150235, None, None, None, None],     # Matterhorn - Monte Cervino, trip report, trip report, route, photo
}
SUMMITPOST = {
    "eight thousander": [],                              # no results
    '"seven summits"': [None, None, None, None, None],   # article, route, trip report, trip report, trip report
    "colorado fourteener": [None, None, None],           # album, trip report, trip report (only 3 results)
    '"high tatras"': [None, None, None, None, None],     # 5 albums
    "matterhorn": [None, None, None, None, None],       # trip report, route, album, album, trip report
}


# ranked list of ids -> P@5, P@10, recall, AP
def metrics(ranked, relevant):
    found = [i for i, doc in enumerate(ranked, 1) if doc in relevant]
    precisions = [(n + 1) / rank for n, rank in enumerate(found)]  # precision at every relevant result
    return {"P@5": len([r for r in found if r <= 5]) / 5,
            "P@10": len([r for r in found if r <= 10]) / 10,
            "R": len(found) / len(relevant),
            "AP": sum(precisions) / len(relevant)}


def old_ranked(index, info, stats, query, method):
    docs, terms = search.matching(index, query, info)
    return [doc for doc, _ in search.results(index, docs, terms, method, len(info), stats, info)]


def new_ranked(searcher, parser, query):
    _, hits = lucene_search.search(searcher, parser, query)
    return [int(doc.get("id")) for _, doc in hits]


def average_ms(run):
    total = 0
    for _ in range(TIMING_RUNS):
        search.postings.__defaults__[0].clear()  # old search caches parsed postings, without this only the 1st run would count
        start = time.perf_counter()
        run()
        total += time.perf_counter() - start
    return total / TIMING_RUNS * 1000


def main():
    lucene.initVM()
    start = time.perf_counter()
    index = search.load_index()
    info = search.load_info()
    stats = search.doc_stats(index, len(info))
    old_load = time.perf_counter() - start
    start = time.perf_counter()
    searcher, parser = lucene_search.open_index()
    new_load = time.perf_counter() - start

    systems = {f"old {m} ({search.RANKINGS[m]})": lambda q, m=m: old_ranked(index, info, stats, q, m)
               for m in search.RANKINGS}
    systems["new (lucene BM25)"] = lambda q: new_ranked(searcher, parser, q)

    lines = []
    totals = {name: {"P@5": 0, "P@10": 0, "R": 0, "AP": 0} for name in list(systems) + ["google", "summitpost"]}
    for query, relevant in QUERIES:
        if callable(relevant):
            relevant = {doc for doc, row in info.items() if relevant(row)}
        lines.append(f"=== {query}   ({len(relevant)} relevant)")
        lines.append(f"    {'system':<36}{'P@5':>6}{'P@10':>6}{'R':>6}{'AP':>7}")
        # all results, not only the first 10, so we can count recall and AP
        search.MAX_MATCHES = lucene_search.MAX_MATCHES = len(info)
        rows = {name: metrics(ranked(query), relevant) for name, ranked in systems.items()}
        for name, hand in (("google", GOOGLE), ("summitpost", SUMMITPOST)):
            if query in hand:
                rows[name] = metrics(hand[query], relevant)
        for name, values in rows.items():
            lines.append(f"    {name:<36}" + "".join(f"{values[k]:>{6 if k != 'AP' else 7}.2f}" for k in values))
            for k in values:
                totals[name][k] += values[k]
        lines.append("")

    lines.append(f"=== average over {len(QUERIES)} queries (AP average = MAP)")
    for name, values in totals.items():
        if name in ("google", "summitpost"):
            count = len(GOOGLE if name == "google" else SUMMITPOST)
            if not count:
                continue
        else:
            count = len(QUERIES)
        label = name if count == len(QUERIES) else f"{name} ({count} queries)"
        lines.append(f"    {label:<36}" + "".join(f"{values[k] / count:>{6 if k != 'AP' else 7}.2f}" for k in values))

    # speed: only the search with the first 10 results, like in the console apps
    search.MAX_MATCHES = lucene_search.MAX_MATCHES = 10
    lines.append("")
    lines.append(f"=== speed (average of {TIMING_RUNS} runs, first 10 results)")
    lines.append(f"    loading: old index {old_load:.2f} s, new index {new_load:.2f} s")
    for query, _ in QUERIES:
        old_ms = average_ms(lambda: old_ranked(index, info, stats, query, 3))
        new_ms = average_ms(lambda: new_ranked(searcher, parser, query))
        lines.append(f"    {query:<24} old {old_ms:8.2f} ms   new {new_ms:8.2f} ms")

    print("\n".join(lines))
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
