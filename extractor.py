import html
import os
import re
import unicodedata

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
HTML_DIR = os.path.join(DATA, "html")
OUT = os.path.join(DATA, "extracted_data.tsv")
COLUMNS = ["id", "name", "country", "continent", "region", "lat", "lon", "elevation_m","activities", "season", "parent", "score", "description"]

# <h1 class="adventure-title m00b ">Rysy</h1>
NAME_RE = re.compile(r'<h1 class="adventure-title[^"]*">(.*?)</h1>', re.S)
# <div class="location"> <a ...> <i ...></i> <span>Tatra Mountains, Poland/Slovakia, Europe</span>
LOCATION_RE = re.compile(r'<div class="location">.*?<span>([^<]*)</span>', re.S)
# <th> <img ...> Elevation: </th> <td>8212 ft / 2503 m</td>  -> one row of the table under the photo
TABLE_ROW_RE = re.compile(r'<th>\s*<img[^>]*>\s*([^<]+?):?\s*</th>\s*<td>(.*?)</td>', re.S)
# 49.18330&deg;N / 20.08330&deg;E  (S and W are negative)
LATLON_RE = re.compile(r'([\d.]+)\s*(?:&deg;|°)\s*([NS])\s*/\s*([\d.]+)\s*(?:&deg;|°)\s*([EW])')
# 8212 ft / 2503 m  -> we take only the meters
ELEVATION_RE = re.compile(r'([\d,]+)\s*m\b')
# <a href="/high-tatras-vysok-tatry/154185" class="head-sub sub2">High Tatras / Vysoké Tatry</a>
PARENT_RE = re.compile(r'class="head-sub sub2">([^<]+)</a>')
# <span id="score">97.89</span>% Score
SCORE_RE = re.compile(r'<span id="score">([\d.]+)</span>')
# start of every chapter: <a name='chapter_1'></a><h2 class="in-title" ...>Intro</h2>
CHAPTER_RE = re.compile(r"<a name=['\"](?:chapter_\d+|messages)['\"]")
# chapter title + where the chapter starts
CHAPTER_TITLE_RE = re.compile(r"<a name='chapter_\d+'></a>\s*<h2[^>]*>([^<]*)")
# titles of the chapter we want as the description
DESCRIPTION_RE = re.compile(r"intro|overview", re.I)
# things in the chapter that are not text: photo captions, thumbnail tables, ads, the chapter title
JUNK_RE = re.compile(r'<span class="caption"[^>]*>.*?</span>'
                     r'|<table class="inline_image_thumbs">.*?</table>'
                     r'|<(script|style|ins)\b.*?</\1>'
                     r'|<h2.*?</h2>', re.S)
TAG_RE = re.compile(r'<[^>]+>')

# letters that dont fall apart into "letter + accent", so we change them by hand
# without this they would just disappear, examples from our pages:
#   Wołowiec (Volovec)        /424291    -> Woowiec      instead of Wolowiec
#   Galdhøpiggen              /150792    -> Galdhpiggen  instead of Galdhopiggen
#   Đeravica / Gjeravica      /173204    -> eravica      instead of Deravica
#   Bettelwurf, Großer        /151399    -> Groer        instead of Grosser
#   Svolværgeita              /152871    -> Svolvrgeita  instead of Svolvaergeita
#   Pu‘u Koa‘e (Puu Koae)     /153012    -> Puu Koae     instead of Pu'u Koa'e
SPECIAL = str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D", "ß": "ss",
                         "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE", "þ": "th", "ð": "d", "ı": "i",
                         "‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "…": "..."})


# Kriva&#328 so we need to change it to Krivan
def clean(text):
    text = html.unescape(TAG_RE.sub(" ", text))           # &#328; = ň, &nbsp; -> space, tags out
    text = unicodedata.normalize("NFKD", text.translate(SPECIAL))  # ň = n + ˇ
    text = text.encode("ascii", "ignore").decode("ascii")  # drop the ˇ and other non ascii chars
    return re.sub(r"\s+", " ", text).strip()               # tabs/newlines so we dont break the TSV


# take the data out of one mountain page
def extract(page_id, page):
    row = dict.fromkeys(COLUMNS, "")
    row["id"] = page_id

    found = NAME_RE.search(page)
    if found:
        row["name"] = clean(found.group(1))

    # "region, country, continent", sometimes only "country, continent", sometimes coordinates
    found = LOCATION_RE.search(page)
    if found and "&deg;" not in found.group(1) and "°" not in found.group(1):
        parts = [p.strip() for p in clean(found.group(1)).split(",") if p.strip()]
        if parts:
            row["continent"] = parts[-1]
        if len(parts) >= 2:
            row["country"] = parts[-2]
        if len(parts) >= 3:
            row["region"] = ", ".join(parts[:-2])

    # table under the photo: Lat/Lon, Elevation, Activities, Season, ...
    start = page.find('class="object-properties-table"')
    table = page[start:page.find("</table>", start)] if start != -1 else ""
    rows = {key.strip(): value for key, value in TABLE_ROW_RE.findall(table)}

    found = LATLON_RE.search(rows.get("Lat/Lon", ""))
    if found:
        lat, ns, lon, ew = found.groups()
        row["lat"] = ("-" if ns == "S" else "") + lat
        row["lon"] = ("-" if ew == "W" else "") + lon

    found = ELEVATION_RE.search(rows.get("Elevation", ""))
    if found:
        row["elevation_m"] = found.group(1).replace(",", "")

    row["activities"] = clean(rows.get("Activities", ""))
    row["season"] = clean(rows.get("Season", ""))

    # first parent in the Parents box is the main one (the range the mountain is in)
    start = page.find('class="side-menu parents"')
    found = PARENT_RE.search(page, start) if start != -1 else None
    if found:
        row["parent"] = clean(found.group(1))

    found = SCORE_RE.search(page)
    if found:
        row["score"] = found.group(1)

    # description = first chapter called "Intro" or "Overview", if there is none we take chapter 1
    # (chapter 1 is sometimes "What's new on the page???" and the real text is in chapter 2)
    chapters = list(CHAPTER_TITLE_RE.finditer(page))
    wanted = [c for c in chapters if DESCRIPTION_RE.search(c.group(1))]
    chosen = wanted[0] if wanted else (chapters[0] if chapters else None)
    if chosen:
        start = chosen.start()
        end = CHAPTER_RE.search(page, start + 1)
        chapter = page[start:end.start() if end else len(page)]
        row["description"] = clean(JUNK_RE.sub(" ", chapter))

    return row


def main():
    files = sorted(f for f in os.listdir(HTML_DIR) if f.endswith(".html"))
    with open(OUT, "w", encoding="utf-8", newline="") as out:
        out.write("\t".join(COLUMNS) + "\n")
        for count, file in enumerate(files, 1):
            with open(os.path.join(HTML_DIR, file), encoding="utf-8") as f:
                row = extract(file[:-5], f.read())
            out.write("\t".join(row[c] for c in COLUMNS) + "\n")
            if count % 500 == 0:
                print(f"{count}/{len(files)}")
    print(f"Done, {len(files)} mountains -> {OUT}")


if __name__ == "__main__":
    main()
