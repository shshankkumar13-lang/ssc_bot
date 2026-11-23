"""
SSC Update Telegram Bot (v2 - uses SSC's JSON API, because ssc.gov.in loads
its notices with JavaScript and plain HTML scraping returns nothing).

Env vars:
  BOT_TOKEN   token from @BotFather
  CHAT_ID     @channelusername or -100xxxxxxxxxx  (bot must be channel admin)
  RUN_ONCE=1  run one check and exit (used by GitHub Actions)
  TEST_MODE=true  only send a test message to the channel and exit
"""

import os
import re
import json
import time
import html
import logging
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "@THEKHUNKHARSOFFICIAL")
CHECK_EVERY_SECONDS = 600
SEEN_FILE = "seen.json"
MAX_POSTS_PER_RUN = 10          # safety: never flood the channel
SEND_PDF_FILES = False          # True = also upload PDF directly to Telegram

API_URL = "https://ssc.gov.in/api/general-website/portal/records"
FILE_BASE = "https://ssc.gov.in/api/attachment/"

# SSC groups its content by "contentType". We try each one and log which work.
CONTENT_TYPES = [
    "Public Notices",
    "Notice Board",
    "Latest News",
    "Results",
    "Answer Keys",
    "Admit Cards",
]

# Old HTML pages as a backup (may return nothing because of JavaScript).
HTML_SOURCES = ["https://ssc.gov.in/"]

FOOTER = (
    "\n\n━━━━━━━━━━━━━━\n"
    "📢 Join @THEKHUNKHARSOFFICIAL for PDF, New Jobs, Answer Key &amp; all updates"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://ssc.gov.in/",
    "Origin": "https://ssc.gov.in",
}

TITLE_KEYS = ("title", "name", "heading", "subject", "noticeTitle", "description")
FILE_RE = re.compile(r"\.(pdf|xlsx?|zip|docx?)(\?.*)?$", re.I)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sscbot")


# ---------------------------------------------------------------- storage
def load_seen():
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            pass
    return None  # None = first run


def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f)


# ---------------------------------------------------------------- fetching
def to_url(path):
    path = str(path).strip()
    if path.startswith("http"):
        return path
    return FILE_BASE + path.lstrip("/")


def find_file_paths(obj):
    """Collect strings inside obj that look like file paths."""
    out = []
    if isinstance(obj, str):
        if FILE_RE.search(obj) or "uploads/" in obj:
            out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            out += find_file_paths(v)
    elif isinstance(obj, list):
        for v in obj:
            out += find_file_paths(v)
    return out


def walk_dicts(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_dicts(v)


def items_from_json(data):
    """Turn any JSON shape into a list of (key, title, link)."""
    items, used = [], set()
    for d in walk_dicts(data):
        title = next((d[k] for k in TITLE_KEYS
                      if isinstance(d.get(k), str) and len(d[k].strip()) > 5), None)
        if not title:
            continue
        paths = find_file_paths(d)
        if not paths:
            continue
        link = to_url(paths[0])
        if link in used:
            continue
        used.add(link)
        items.append((link, " ".join(title.split()), link))
    return items


def fetch_api():
    results = []
    for ctype in CONTENT_TYPES:
        try:
            r = requests.get(
                API_URL,
                params={"contentType": ctype, "page": 1, "pageSize": 50},
                headers=HEADERS, timeout=40,
            )
            log.info("API [%s] -> HTTP %s, %s bytes", ctype, r.status_code, len(r.content))
            if not r.ok:
                log.info("   body start: %s", r.text[:200].replace("\n", " "))
                continue
            found = items_from_json(r.json())
            log.info("   found %d items", len(found))
            results += found
        except Exception as e:
            log.warning("API [%s] failed: %s", ctype, e)
    return results


def fetch_html():
    results = []
    for url in HTML_SOURCES:
        try:
            r = requests.get(url, headers={**HEADERS, "Accept": "text/html"}, timeout=40)
            r.raise_for_status()
        except Exception as e:
            log.warning("HTML fetch failed %s: %s", url, e)
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            title = " ".join(a.get_text(" ", strip=True).split())
            full = urljoin(url, a["href"].strip())
            if len(title) > 8 and FILE_RE.search(full):
                results.append((full, title, full))
    log.info("HTML backup found %d items", len(results))
    return results


# ---------------------------------------------------------------- telegram
def tg(method, **payload):
    r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
                      data=payload, timeout=60)
    if not r.ok:
        log.error("Telegram error: %s", r.text)
    return r.ok


def category(title):
    t = title.lower()
    if "answer key" in t:
        return "🔑 ANSWER KEY"
    if "admit card" in t or "city" in t and "slip" in t:
        return "🎫 ADMIT CARD"
    if any(k in t for k in ("result", "scorecard", "cut off", "cutoff", "marks")):
        return "🏆 RESULT"
    if any(k in t for k in ("notice of", "recruitment", "vacancy", "vacancies", "advertisement")):
        return "💼 NEW JOB"
    return "📌 SSC UPDATE"


def post(title, link):
    text = (
        f"<b>{category(title)}</b>\n\n"
        f"{html.escape(title)}\n\n"
        f'🔗 <a href="{html.escape(link)}">Open / Download</a>'
        f"{FOOTER}"
    )
    ok = tg("sendMessage", chat_id=CHAT_ID, text=text, parse_mode="HTML",
            disable_web_page_preview="true")
    if ok and SEND_PDF_FILES and link.lower().endswith(".pdf"):
        tg("sendDocument", chat_id=CHAT_ID, document=link,
           caption="📢 Join @THEKHUNKHARSOFFICIAL")
    time.sleep(3)


# ---------------------------------------------------------------- main logic
def run_once(seen, first_run):
    items = fetch_api() or fetch_html()
    if not items:
        log.error("NO ITEMS FOUND from SSC. Nothing saved. Check the log lines above "
                  "(HTTP status / blocked / wrong contentType).")
        return seen

    new = [i for i in items if i[0] not in seen]
    log.info("Total items: %d | new: %d | first_run=%s", len(items), len(new), first_run)

    if not first_run:
        to_post = new[:MAX_POSTS_PER_RUN]
        for key, title, link in reversed(to_post):   # oldest first
            post(title, link)

    for key, _, _ in new:
        seen.add(key)
    save_seen(seen)
    return seen


def main():
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is missing. Add it in GitHub Secrets.")

    if os.getenv("TEST_MODE", "").lower() == "true":
        ok = tg("sendMessage", chat_id=CHAT_ID, parse_mode="HTML",
                text="✅ <b>Test message</b>\n\nBot is connected to this channel." + FOOTER)
        log.info("Test message sent: %s", ok)
        return

    seen = load_seen()
    first_run = seen is None
    seen = seen or set()
    if first_run:
        log.info("First run: saving existing items without posting.")

    if os.getenv("RUN_ONCE") == "1":
        run_once(seen, first_run)
        return

    while True:
        try:
            seen = run_once(seen, first_run)
            first_run = False
        except Exception as e:
            log.exception("Loop error: %s", e)
        time.sleep(CHECK_EVERY_SECONDS)


if __name__ == "__main__":
    main()
