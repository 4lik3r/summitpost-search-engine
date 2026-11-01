import os
import re

import lucene
from java.lang import Float, Integer
from java.nio.file import Paths
from java.util import HashMap
from org.apache.lucene.document import IntPoint
from org.apache.lucene.index import DirectoryReader
from org.apache.lucene.queryparser.classic import MultiFieldQueryParser, QueryParser, QueryParserBase
from org.apache.lucene.search import BooleanClause, BooleanQuery, IndexSearcher, MatchAllDocsQuery, Sort, SortField
from org.apache.lucene.store import FSDirectory

from lucene_index import INDEX, TEXT_FIELDS, analyzer

MAX_MATCHES = 10  # how many results we show
# a word in the name is worth more than the same word somewhere in the description
BOOSTS = {"name": 3.0, "other_name": 2.0, "wiki_title": 2.0}

# elevation>5000, prominence>=1500, ascent<1900 = range filter on a number field
FILTER_RE = re.compile(r'(elevation|prominence|ascent)\s*(<=|>=|<|>|=)\s*(\d+)', re.I)
FILTER_FIELDS = {"elevation": "elevation", "prominence": "prominence", "ascent": "ascent_year"}


def open_index():
    searcher = IndexSearcher(DirectoryReader.open(FSDirectory.open(Paths.get(INDEX))))
    boosts = HashMap()
    for field, boost in BOOSTS.items():
        boosts.put(field, Float(boost))
    # the words are searched in all text fields at once, space = AND like in the old search.py
    parser = MultiFieldQueryParser(TEXT_FIELDS, analyzer(), boosts)
    parser.setDefaultOperator(QueryParser.Operator.AND)
    return searcher, parser


# "elevation", ">", 5000 -> IntPoint range query (elevation from 5001 up)
def range_query(field, op, value):
    if op == "=":
        return IntPoint.newExactQuery(field, value)
    low, high = {"<": (Integer.MIN_VALUE, value - 1), "<=": (Integer.MIN_VALUE, value),
                 ">": (value + 1, Integer.MAX_VALUE), ">=": (value, Integer.MAX_VALUE)}[op]
    return IntPoint.newRangeQuery(field, low, high)


# whole query -> lucene query + if the results should be sorted by elevation (only filters, no words)
#   words: lucene query syntax (AND, OR, NOT, "phrase", krivan~, annapur*, country:nepal)
#   filters: taken out first, they are FILTER clauses = must match but don't change the score
def build_query(parser, query):
    filters = FILTER_RE.findall(query)
    words = FILTER_RE.sub(" ", query).strip()
    builder = BooleanQuery.Builder()
    # QueryParserBase.parse(parser, ...) and not parser.parse(...): in pylucene the static
    # MultiFieldQueryParser.parse() hides the normal one
    builder.add(QueryParserBase.parse(parser, words) if words else MatchAllDocsQuery(), BooleanClause.Occur.MUST)
    for name, op, value in filters:
        builder.add(range_query(FILTER_FIELDS[name.lower()], op, int(value)), BooleanClause.Occur.FILTER)
    return builder.build(), not words


# query -> (number of matches, [(score, document), ...]) ranked by BM25 (lucene default)
def search(searcher, parser, query):
    lucene_query, by_elevation = build_query(parser, query)
    if by_elevation:
        top = searcher.search(lucene_query, MAX_MATCHES, Sort(SortField("elevation", SortField.Type.INT, True)))
    else:
        top = searcher.search(lucene_query, MAX_MATCHES)
    stored = searcher.storedFields()
    hits = []
    for hit in top.scoreDocs:
        doc = stored.document(hit.doc)
        score = float(doc.get("elevation")) if by_elevation else hit.score
        hits.append((score, doc))
    return searcher.count(lucene_query), hits


def main():
    lucene.initVM()
    searcher, parser = open_index()
    print(f"{searcher.getIndexReader().numDocs()} mountains in the lucene index")
    print('Query: words (space = AND), OR, NOT, "phrase", word~ (fuzzy), word* (prefix), field:word,')
    print('       elevation>5000, prominence>=1500, ascent<1900 (< > <= >= =), empty = quit')

    while True:
        query = input("\nquery> ").strip()
        if not query:
            break
        try:
            count, hits = search(searcher, parser, query)
        except lucene.JavaError as e:  # bad lucene syntax, for example a missing "
            print("Bad query:", e.getJavaException().getMessage())
            continue
        print(f"{count} documents match")
        for place, (score, doc) in enumerate(hits, 1):
            wiki = f"  [wiki: {doc.get('wiki_title')}]" if doc.get("wiki_title") else ""
            print(f"{place:>2}. {score:8.3f}  {doc.get('name')[:35]:<37}{doc.get('elevation') or '':>6} m"
                  f"  {doc.get('country') or ''}{wiki}")


if __name__ == "__main__":
    main()
