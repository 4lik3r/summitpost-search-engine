import os

from pyspark.sql import SparkSession

from extractor import COLUMNS, extract

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
HTML_DIR = os.path.join(DATA, "html")
OUT = os.path.join(DATA, "spark", "summitpost")


# html file -> list of the extracted values, same extract() as in extractor.py
def extract_file(file):
    with open(os.path.join(HTML_DIR, file), encoding="utf-8") as f:
        row = extract(file[:-len(".html")], f.read())
    return [row[column] for column in COLUMNS]


def main():
    spark = SparkSession.builder.appName("summitpost-extract").getOrCreate()

    # spark gets the list of file names and splits it between the cores, every worker opens its own files
    # (wholeTextFiles was too slow, hadoop checks every one of the 9221 small files separately)
    files = sorted(f for f in os.listdir(HTML_DIR) if f.endswith(".html"))
    rows = spark.sparkContext.parallelize(files, 48).map(extract_file)

    df = spark.createDataFrame(rows, COLUMNS).cache()  # cache so count() at the end doesnt extract everything again
    # one tab separated file with a header, quote="" so spark doesnt put quotes around the texts
    # repartition(1) and not coalesce(1): coalesce would do the whole work in one task, not in parallel
    (df.repartition(1).write.mode("overwrite")
       .option("sep", "\t").option("header", True).option("quote", "").option("escape", "")
       .option("emptyValue", "")  # empty value = nothing, spark writes "" by default
       .csv(OUT))

    print(f"Done, {df.count()} mountains -> {OUT}")
    spark.stop()


if __name__ == "__main__":
    main()
