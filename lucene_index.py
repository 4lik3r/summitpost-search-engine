import glob
import os
import re

import lucene
from java.nio.file import Paths
from org.apache.lucene.analysis.en import EnglishAnalyzer
from org.apache.lucene.document import (Document, Field, IntPoint, NumericDocValuesField, StoredField, StringField,
                                        TextField)
from org.apache.lucene.index import IndexWriter, IndexWriterConfig
from org.apache.lucene.store import FSDirectory

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
JOINED = os.path.join(DATA, "spark", "joined")  # output of spark_join.py: summitpost + wiki columns
INDEX = os.path.join(DATA, "lucene_index")

# text fields: field name in the index -> column in the joined file
# stored = we show it in the results, the rest is only searched (saves space)
STORED_TEXT = {"name": "name", "other_name": "other_name", "wiki_title": "wiki_title",
               "country": "country", "continent": "continent", "region": "region", "parent": "parent"}
SEARCHED_TEXT = {"activities": "activities", "season": "season",
                 "mountain_range": "range", "type": "type", "listing": "listing",   # "range" would clash with range queries
                 "first_ascent": "first_ascent", "easiest_route": "easiest_route",
                 "etymology": "etymology", "last_eruption": "last_eruption",
                 "description": "description", "lead": "lead"}
TEXT_FIELDS = list(STORED_TEXT) + list(SEARCHED_TEXT)

# "31 August 1844 by Melchior Bannholzer" -> 1844 (the first year in the text)
YEAR_RE = re.compile(r"\b(1[5-9]\d\d|20\d\d)\b")


# lucene uses the same analyzer for indexing and for the queries (search imports it from here)
# EnglishAnalyzer = lowercase + english stopwords + porter stemming (peaks -> peak, climbing -> climb)
def analyzer():
    return EnglishAnalyzer()


# "2594" / "4478.0" / "" -> 2594 / 4478 / None
def number(value):
    try:
        return int(float(value))
    except ValueError:
        return None


# one row of the joined file -> one lucene document (one mountain)
def make_document(row):
    doc = Document()
    doc.add(StringField("id", row["id"], Field.Store.YES))  # exact, not analyzed
    for field, column in STORED_TEXT.items():
        if row[column]:
            doc.add(TextField(field, row[column], Field.Store.YES))
    for field, column in SEARCHED_TEXT.items():
        if row[column]:
            doc.add(TextField(field, row[column], Field.Store.NO))

    # numbers: IntPoint = for range queries, StoredField = to show the value in the results
    year = YEAR_RE.search(row["first_ascent"])
    numbers = {"elevation": number(row["elevation_m"]) or number(row["wiki_elevation_m"]),  # summitpost, else wiki
               "prominence": number(row["prominence_m"]),
               "ascent_year": int(year.group(1)) if year else None}
    for field, value in numbers.items():
        if value is not None:
            doc.add(IntPoint(field, value))
            doc.add(StoredField(field, value))
    # doc values = so lucene can sort by elevation (query with only a filter -> highest mountains first)
    if numbers["elevation"] is not None:
        doc.add(NumericDocValuesField("elevation", numbers["elevation"]))
    return doc


def read_joined():
    path = glob.glob(os.path.join(JOINED, "part-*.csv"))[0]  # spark writes one part file
    with open(path, encoding="utf-8") as f:
        columns = f.readline().rstrip("\n").split("\t")
        for line in f:
            yield dict(zip(columns, line.rstrip("\n").split("\t")))


def main():
    lucene.initVM()
    config = IndexWriterConfig(analyzer())
    config.setOpenMode(IndexWriterConfig.OpenMode.CREATE)  # always build the whole index again
    writer = IndexWriter(FSDirectory.open(Paths.get(INDEX)), config)
    for row in read_joined():
        writer.addDocument(make_document(row))
    writer.commit()
    print(f"Done, {writer.getDocStats().numDocs} documents -> {INDEX}")
    writer.close()


if __name__ == "__main__":
    main()
