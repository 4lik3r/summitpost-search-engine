import os

import lucene

import search
from lucene_search import open_index
from lucene_search import search as lucene_search

OUT = os.path.join(search.DATA, "compare.txt")
SHOWN = 5         # top results per index in the output
OLD_METHOD = 3    # old ranking: euclid normalization tf * idf (same as on the Odovzdanie 1 wiki)

# the same text is typed into both systems
QUERIES = [
    # the 5 questions from Odovzdanie 1
    "matterhorn",
    '"mount whitney"',
    "volcano mexico elevation>5000",
    'kilimanjaro OR "mount kenya"',
    'colorado "class 3" NOT "class 4" elevation>=4267',
    # things only the new index can do
    "glaciers",                      # stemming: glaciers = glacier
    "matterhon~",                    # fuzzy: typo
    "annapur*",                      # prefix
    "tumanguya",                     # other name from wiki (mount whitney), not on summitpost
    "type:stratovolcano",            # wiki attribute as a field
    "ascent<1900 elevation>6000",    # range on the wiki first ascent year
]


def main():
    lucene.initVM()
    searcher, parser = open_index()
    index = search.load_index()
    info = search.load_info()
    n = len(info)
    stats = search.doc_stats(index, n)

    lines = []
    for query in QUERIES:
        docs, terms = search.matching(index, query, info)
        old = [(score, info[doc]["name"]) for doc, score in
               search.results(index, docs, terms, OLD_METHOD, n, stats, info)][:SHOWN]
        count, hits = lucene_search(searcher, parser, query)
        new = [(score, doc.get("name")) for score, doc in hits][:SHOWN]

        lines.append(f"=== {query}")
        lines.append(f"    {'old index: ' + str(len(docs)) + ' matches':<45}new index: {count} matches")
        for place in range(max(len(old), len(new))):
            cells = ""
            for ranked in (old, new):
                cells += f"{ranked[place][0]:8.3f} {ranked[place][1][:34]:<36}" if place < len(ranked) else " " * 45
            lines.append(f"{place + 1:>2}. {cells}")
        lines.append("")

    print("\n".join(lines))
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
