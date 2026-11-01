import os
import re

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
EXTRACTED = os.path.join(DATA, "extracted_data.tsv")
INDEX = os.path.join(DATA, "index.tsv")

# text columns from extracted_data.tsv that go into the index (numbers like elevation stay out, they are for filters)
TEXT_COLUMNS = ["name", "parent", "region", "country", "continent", "activities", "season", "description"]

# We remove whitespace and interpunction)
TOKEN_RE = re.compile(r"[a-z0-9]+")
# We remove stop words (src: https://gist.github.com/sebleier/554280)
STOPWORDS = {
    "i", "me", "my", "myself", "we", "our", "ours", "ourselves", "you", "your", "yours", "yourself",
    "yourselves", "he", "him", "his", "himself", "she", "her", "hers", "herself", "it", "its", "itself",
    "they", "them", "their", "theirs", "themselves", "what", "which", "who", "whom", "this", "that",
    "these", "those", "am", "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "having", "do", "does", "did", "doing", "a", "an", "the", "and", "but", "if", "or", "because", "as",
    "until", "while", "of", "at", "by", "for", "with", "about", "against", "between", "into", "through",
    "during", "before", "after", "above", "below", "to", "from", "up", "down", "in", "out", "on", "off",
    "over", "under", "again", "further", "then", "once", "here", "there", "when", "where", "why", "how",
    "all", "any", "both", "each", "few", "more", "most", "other", "some", "such", "no", "nor", "not",
    "only", "own", "same", "so", "than", "too", "very", "s", "t", "can", "will", "just", "don", "should",
    "now"}


# text = list of (position, term), stopwords are skipped but still count as a position
# so the phrase "summit of mount" still has the right distance between summit and mount
def tokenize(text, start=0):
    tokens = []
    for position, term in enumerate(TOKEN_RE.findall(text.lower()), start):
        if term not in STOPWORDS:
            tokens.append((position, term))
    return tokens


def main():
    index = {}  # term -> {doc_id: [positions]}
    count = 0   # number of documents

    with open(EXTRACTED, encoding="utf-8") as f:
        columns = f.readline().rstrip("\n").split("\t")
        for line in f:
            row = dict(zip(columns, line.rstrip("\n").split("\t")))
            doc_id = row["id"]

            # all text columns one after another, +1 gap between them so a phrase
            # cant start in the name and end in the parent
            position = 0
            for column in TEXT_COLUMNS:
                tokens = tokenize(row.get(column, ""), position)
                for pos, term in tokens:
                    index.setdefault(term, {}).setdefault(doc_id, []).append(pos)
                position += len(TOKEN_RE.findall(row.get(column, "").lower())) + 1
            count += 1

    # index.tsv: term  df  doc_id:pos,pos,pos  doc_id:pos,...   (tf = term frequency)
    # terms alphabetically, documents by id, so we can merge the posting lists later
    with open(INDEX, "w", encoding="utf-8", newline="") as out:
        for term in sorted(index):
            postings = index[term]
            parts = [doc_id + ":" + ",".join(map(str, postings[doc_id])) for doc_id in sorted(postings, key=int)]
            out.write(f"{term}\t{len(postings)}\t" + "\t".join(parts) + "\n")

    print(f"Done, {count} documents, {len(index)} terms -> {INDEX}")


if __name__ == "__main__":
    main()
