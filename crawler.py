import os
import re
import time
import urllib.error
import urllib.request

BASE = "https://www.summitpost.org"
# we start on mount Everest and go through the links on the pages (parents, children, nearby mountains).
# we wanted to go through the mountain list (/mountain/rock/ has 645 pages, 15471 mountains), but the site
# returns 403 for all list pages except the first one (they are only for browsers), so we follow links instead.
START_URL = BASE + "/mount-everest/150230"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}
DELAY = 1.0          # 1 second request time so we dont proc cloudflare
TIMEOUT = 15         # 15 seconds per request so we dont get stuck

# mountains are mainly saved, areas and lists are only used to get to other mountains
SAVE_TYPES = {"Mountain/Rock"}
FOLLOW_TYPES = {"Mountain/Rock", "Area/Range", "List"}

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
TO_VISIT = os.path.join(DATA, "to_visit.txt")
VISITED = os.path.join(DATA, "visited.txt")
LOG = os.path.join(DATA, "crawl_log.tsv")

# <a href="/gerlachovsky-stit/150749">Gerlachovsky Stit</a>  -> link to another page (url also needs digits because K2 :D)
# <a href='/aconcagua/150197'>Aconcagua</a>                  -> the site uses both " and ' around links
# <a href="/gerlach-from-the-south/123456"><img ...>         -> photo thumbnail, the second group catches the <img
LINK_RE = re.compile(r'href=["\'](/[a-z0-9-]+/\d+)["\'][^>]*>\s*(<img)?')
# <a href="/matterhorn-monte-cervino/mountains-rocks/p-155314"> 196&nbsp;More </a>  -> all mountains of one parent
MORE_RE = re.compile(r'href=["\'](/[a-z0-9-]+/mountains-rocks/p-\d+)["\']')
# <th>Page Type:</th> <td>Mountain/Rock</td>  -> what kind of page it is
PAGE_TYPE_RE = re.compile(r'Page Type:?\s*</[^>]+>\s*(?:<[^>]+>\s*)*([^<]+)')


# read a text file into a list of lines (empty list if the file doesnt exist yet)
def read_lines(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


# download one page and return its status code and html
def download(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.status, resp.read().decode("utf-8", errors="replace")


# the id is the end of the url: /mount-everest/150230 -> 150230
def page_id(url):
    return url.rsplit("/", 1)[1]


def main():
    # create the output folder if it doesnt exist for first run
    os.makedirs(os.path.join(DATA, "html"), exist_ok=True)
    os.makedirs(os.path.join(DATA, "more"), exist_ok=True)

    # load the state from the last run when we crawl by a few sessions, or start at mount Everest
    to_visit = read_lines(TO_VISIT) or [START_URL]
    visited = set(read_lines(VISITED))
    # ids of every page we already have, so we dont add it twice
    # (the same mountain can have 2 urls: /everest/150230 and /mount-everest/150230)
    known = {page_id(u) for u in visited | set(to_visit)}

    visited_file = open(VISITED, "a", encoding="utf-8")
    log = open(LOG, "a", encoding="utf-8")
    if log.tell() == 0:
        #  write the header to log file so its readable
        log.write("time\tstatus\tpage_type\tbytes\tfile\turl\n")
    count = 0
    failures = {}  # (url, number_of_failed_times) so we dont get stuck in a loop

    try:
        while to_visit:
            # take the first url from the queue and check if it isnt already downloaded
            url = to_visit.pop(0)
            if url in visited:
                continue

            try:
                status, page = download(url)
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503):
                    # server is busy so we wait and try this page again at the end (max 3 times)
                    print(f"HTTP {e.code}, waiting 30 s")
                    failures[url] = failures.get(url, 0) + 1
                    if failures[url] < 3:
                        to_visit.append(url)
                    time.sleep(30)
                else:
                    # if error 403, 404, etc.. we skip this page
                    print(f"HTTP {e.code} {url}")
                    visited.add(url)
                    visited_file.write(url + "\n")
                continue
            except Exception as e:
                # network error, try it again at the end (max 3 times)
                print(f"ERROR {url}: {e}")
                failures[url] = failures.get(url, 0) + 1
                if failures[url] < 3:
                    to_visit.append(url)
                time.sleep(DELAY)
                continue

            # what kind of page is it? (Mountain/Rock, Area/Range, Route, ...)
            if "/mountains-rocks/" in url:
                page_type = "More list"  # full list of one parent's mountains (it has no page type of its own)
            else:
                found = PAGE_TYPE_RE.search(page)
                page_type = found.group(1).strip() if found else "-"

            # mountain page - we save it as <id>.html
            # we keep everything we crawl: mountain page -> html/<id>.html, everything else
            # (lists, areas, "More" lists, ...) -> more/<id>.html
            folder = "html" if page_type in SAVE_TYPES else "more"
            file = os.path.join(folder, page_id(url) + ".html")
            # newline="",windows was changing \n to \r\n, now the file is exactly what is on the site
            with open(os.path.join(DATA, file), "w", encoding="utf-8", newline="") as f:
                f.write(page)

            # which part of the page we take the links from
            if page_type == "More list":
                part = page  # the whole page is a list of mountains
            elif page_type in FOLLOW_TYPES:
                # only the Parents box (from "side-menu parents" to the next box "side-menu friends")
                start = page.find('class="side-menu parents"')
                end = page.find('class="side-menu friends"', start)
                part = page[start:end] if start != -1 and end != -1 else ""
            else:
                part = ""  # route, trip report, photo... we dont follow its links

            # take the mountain/parent links and the "More" links, add the new ones to the end of the queue
            links = [link for link, img in LINK_RE.findall(part) if not img]  # no photo thumbnails
            links += MORE_RE.findall(part)
            for link in links:
                # id = end of the url (150230, p-155314), the same page can have more urls
                if page_id(link) not in known:
                    known.add(page_id(link))
                    to_visit.append(BASE + link)

            # mark the url as visited and write a row to the log (metadata)
            visited.add(url)
            visited_file.write(url + "\n")
            now = time.strftime("%Y-%m-%d %H:%M:%S")       # readable date and time
            size = len(page.encode("utf-8"))                # size in bytes
            log.write(f"{now}\t{status}\t{page_type}\t{size}\t{file}\t{url}\n")
            count += 1
            print(f"[{count}] {status} {page_type:<14} {len(to_visit)} left  {url}")

            # every 20 pages save the queue to disk so we dont lose much if it crashes
            if count % 20 == 0:
                with open(TO_VISIT, "w", encoding="utf-8") as f:
                    f.write("\n".join(to_visit))
                visited_file.flush()
                log.flush()
            time.sleep(DELAY)
    except KeyboardInterrupt:
        print("Stopped, run again to continue")
    finally:
        # always save the queue when the program ends
        with open(TO_VISIT, "w", encoding="utf-8") as f:
            f.write("\n".join(to_visit))
        visited_file.close()
        log.close()


if __name__ == "__main__":
    main()
