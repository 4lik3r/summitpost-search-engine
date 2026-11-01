import math
import os
import re
from collections import Counter

from index import tokenize

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
INDEX = os.path.join(DATA, "index.tsv")
EXTRACTED = os.path.join(DATA, "extracted_data.tsv")

MAX_MATCHES = 10  # how many results we show for every ranking method
RANKINGS = {1: "log tf (wf) * idf", 2: "max tf norm * idf", 3: "euclid norm tf * idf"}
ALPHA = 0.5  # scaling coefficient for the max tf normalization,we use 0.5 like in the lecture

# query -> parts: "mount whitney", AND, OR, NOT, or a normal word
QUERY_RE = re.compile(r'"[^"]*"|\S+')
OPERATORS = {"AND", "OR", "NOT"}
# elevation>5000, elevation <= 2000, elevation=8849 = filter on the elevation_m column (in meters)
FILTER_RE = re.compile(r'elevation\s*(<=|>=|<|>|=)\s*(\d+)', re.I)
COMPARE = {"<": lambda a, b: a < b, ">": lambda a, b: a > b, "<=": lambda a, b: a <= b,
           ">=": lambda a, b: a >= b, "=": lambda a, b: a == b}


# load index.tsv into memory: term -> (df, ["doc:pos,pos", ...]), the postings are parsed only when we need them
def load_index():
    index = {}
    with open(INDEX, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            index[parts[0]] = (int(parts[1]), parts[2:])
    return index


# "150227:1,18,66" -> {150227: [1, 18, 66]}  (doc ids as numbers so they sort right)
# cache = the default {} is created only once, so every term is parsed only the first time we need it
def postings(index, term, cache={}):
    if term not in cache:
        cache[term] = {}
        for part in index.get(term, (0, []))[1]:
            doc, positions = part.split(":")
            cache[term][int(doc)] = [int(p) for p in positions.split(",")]
    return cache[term]


# idf = log(N / df), log base 10 like in the lecture
def idf(index, term, n):
    return math.log10(n / index[term][0]) if term in index else 0.0


# two numbers for every document, we need all its terms for them so we count them once at the start:
# length = sqrt(w1^2 + w2^2 + ... + wn^2), w = tf * idf    -> for the euclid normalization
# tf_max = tf of the most common term in the document      -> for the max tf normalization
def doc_stats(index, n):
    lengths = Counter()
    tf_max = Counter()
    for term, (df, parts) in index.items():
        weight = math.log10(n / df)
        for part in parts:
            doc = int(part[:part.index(":")])
            tf = part.count(",") + 1  # number of positions = tf
            lengths[doc] += (tf * weight) ** 2
            tf_max[doc] = max(tf_max[doc], tf)
    return {doc: math.sqrt(total) for doc, total in lengths.items()}, tf_max


# Boolean part: which documents match

# intersection of two sorted posting lists (merge algorithm from lecture)
def intersect(p1, p2):
    answer = []
    i = j = 0
    while i < len(p1) and j < len(p2):
        if p1[i] == p2[j]:
            answer.append(p1[i])
            i += 1
            j += 1
        elif p1[i] < p2[j]:
            i += 1
        else:
            j += 1
    return answer


# documents with the words right after each other, using the positions
# "summit of mount" -> summit at p, mount at p+2 (of is a stopword but still has a position)
def phrase_docs(index, tokens):
    first = tokens[0][0]
    terms = [(pos - first, term) for pos, term in tokens]  # (offset from the first word, term)
    if any(term not in index for _, term in terms):
        return []
    docs = sorted(postings(index, terms[0][1]))
    for _, term in terms[1:]:
        docs = intersect(docs, sorted(postings(index, term)))
    answer = []
    for doc in docs:
        starts = postings(index, terms[0][1])[doc]
        if any(all(p + offset in postings(index, term)[doc] for offset, term in terms) for p in starts):
            answer.append(doc)
    return answer


# one operand of the query -> sorted list of documents (a word or a "phrase")
def operand_docs(index, text):
    tokens = tokenize(text.strip('"'))
    if not tokens:
        return None  # only stopwords, ignore it
    if len(tokens) == 1:
        return sorted(postings(index, tokens[0][1]))
    return phrase_docs(index, tokens)


# go through the query from left to right: space = AND, OR = union, NOT = remove these documents
# returns the matching documents and the terms we use for ranking (NOT terms are not used)
def boolean_search(index, query):
    result = None
    operator = "AND"
    rank_terms = []
    for part in QUERY_RE.findall(query):
        if part in OPERATORS:
            operator = "AND NOT" if part == "NOT" else part
            continue
        docs = operand_docs(index, part)
        if docs is None:
            continue
        if operator != "AND NOT":
            rank_terms += [term for _, term in tokenize(part.strip('"'))]
        if result is None:
            result = docs if operator != "AND NOT" else []
        elif operator == "AND":
            result = intersect(result, docs)
        elif operator == "OR":
            result = sorted(set(result) | set(docs))
        else:
            result = sorted(set(result) - set(docs))
        operator = "AND"  # back to the default operator
    return result or [], rank_terms


# --- ranking: in what order we show the matching documents -------------------------------

# Score(q,d) = sum over the query terms of the weight of the term in the document (overlap score)
def rank(index, docs, terms, method, n, stats):
    lengths, tf_max = stats
    scores = Counter()
    for term in set(terms):
        weight = idf(index, term, n)
        found = postings(index, term)
        for doc in docs:
            tf = len(found.get(doc, []))
            if tf == 0:
                continue
            if method == 1:
                # logarithmic scaling: wf = 1 + log(tf)  ->  wf * idf
                scores[doc] += (1 + math.log10(tf)) * weight
            elif method == 2:
                # max tf normalization: ntf = a + (1 - a) * tf / tf_max(d)  ->  ntf * idf
                scores[doc] += (ALPHA + (1 - ALPHA) * tf / tf_max[doc]) * weight
            else:
                # document length, euclid normalization: tf * idf / sqrt(w1^2 + ... + wn^2)
                scores[doc] += tf * weight / lengths[doc]
    return scores.most_common(MAX_MATCHES)


# --- elevation filter -------------------------------------------------------------------

# whole query -> matching documents + terms for ranking, the elevation filters are taken out of the query first
def matching(index, query, info):
    filters = [(op, int(value)) for op, value in FILTER_RE.findall(query)]
    words = FILTER_RE.sub(" ", query)
    docs, terms = boolean_search(index, words)
    if filters:
        if not QUERY_RE.findall(words):
            docs = sorted(info)  # only a filter, no words -> start with all mountains
        # keep only mountains whose elevation passes all filters (no elevation on the page = out)
        docs = [doc for doc in docs if info[doc]["elevation_m"]
                and all(COMPARE[op](int(info[doc]["elevation_m"]), value) for op, value in filters)]
    return docs, terms


# ranked results, or if there are no words to rank by (only a filter) the highest mountains first
def results(index, docs, terms, method, n, stats, info):
    if terms:
        return rank(index, docs, terms, method, n, stats)
    highest = sorted(docs, key=lambda doc: int(info[doc]["elevation_m"] or 0), reverse=True)
    return [(doc, float(info[doc]["elevation_m"] or 0)) for doc in highest[:MAX_MATCHES]]


# --- console ------------------------------------------------------------------------------

# extracted_data.tsv -> {id: row}, for the names and elevations in the results and for the filter
def load_info():
    info = {}
    with open(EXTRACTED, encoding="utf-8") as f:
        columns = f.readline().rstrip("\n").split("\t")
        for line in f:
            row = dict(zip(columns, line.rstrip("\n").split("\t")))
            info[int(row["id"])] = row
    return info


def main():
    print("Loading index ...")
    index = load_index()
    info = load_info()
    n = len(info)
    stats = doc_stats(index, n)
    print(f"{n} mountains, {len(index)} terms")
    print('Query: words (space = AND), OR, NOT, "phrase", elevation>5000 (< > <= >= =), empty = quit')

    while True:
        query = input("\nquery> ").strip()
        if not query:
            break
        docs, terms = matching(index, query, info)
        print(f"{len(docs)} documents match")

        # the same matches ranked with all three methods, side by side
        columns = [results(index, docs, terms, method, n, stats, info) for method in RANKINGS]
        print("    " + "".join(f"{RANKINGS[method]:<40}" for method in RANKINGS))
        for place in range(max(len(ranked) for ranked in columns)):
            cells = ""
            for ranked in columns:
                if place < len(ranked):
                    doc, score = ranked[place]
                    cells += f"{score:7.3f} {info[doc]['name'][:30]:<32}"
                else:
                    cells += " " * 40
            print(f"{place + 1:>2}. {cells}")


if __name__ == "__main__":
    main()
