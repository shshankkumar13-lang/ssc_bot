"""
SSC Update Telegram Bot
-----------------------
Watches SSC pages for new notices / answer keys / results / admit cards
and posts them to your Telegram channel with a footer.

Setup:
  pip install requests beautifulsoup4
  export BOT_TOKEN="123456:ABC..."        # from @BotFather
  export CHAT_ID="@YourChannelUsername"   # or -100xxxxxxxxxx (bot must be channel ADMIN)
  python ssc_bot.py
"""

import os
import json
import time
import html
import logging
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BOT_TOKEN = os.getenv("BOT_TOKEN", "PUT_BOT_TOKEN_HERE")
CHAT_ID = os.getenv("CHAT_ID", "@THEKHUNKHARSOFFICIAL")
CHECK_EVERY_SECONDS = 600          # check every 10 minutes
SEEN_FILE = "seen.json"
SEND_PDF_FILES = False             # True = also upload PDF directly to Telegram

# Pages to watch. Add or remove as you like.
SOURCES = [
    "https://ssc.gov.in/",
    "https://ssc.gov.in/portal/notice-board",
    "https://ssc.gov.in/portal/answer-key",
    "https://ssc.gov.in/portal/result",
    "https://ssc.gov.in/portal/admit-card",
]

KEYWORDS = [
    "notice", "answer key", "result", "admit card", "exam", "cgl", "chsl",
    "mts", "gd", "constable", "cpo", "stenographer", "selection post",
    "junior engineer", "je", "recruitment", "vacancy", "schedule",
    "tentative", "cut off", "cutoff", "final", "scorecard", "revised", "date",
]

FOOTER = (
    "\n\n━━━━━━━━━━━━━━\n"
    "📢 Join @THEKHUNKHARSOFFICIAL for PDF, New Jobs, Answer Key &amp; all updates"
)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sscbot")


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


def fetch_links(url):
    """Return list of (title, absolute_url) found on a page."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
    except Exception as e:
        log.warning("Fetch failed %s: %s", url, e)
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    found = []
    for a in soup.find_all("a", href=True):
        title = " ".join(a.get_text(" ", strip=True).split())
        href = a["href"].strip()
        if not title or len(title) < 8 or href.startswith(("#", "javascript", "mailto")):
            continue
        full = urljoin(url, href)
        low = title.lower()
        if full.lower().endswith(".pdf") or any(k in low for k in KEYWORDS):
            found.append((title, full))
    return found


def tg(method, **payload):
    r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}", data=payload, timeout=60)
    if not r.ok:
        log.error("Telegram error: %s", r.text)
    return r.ok


def category(title):
    t = title.lower()
    if "answer key" in t:
        return "🔑 ANSWER KEY"
    if "admit card" in t:
        return "🎫 ADMIT CARD"
    if "result" in t or "scorecard" in t or "cut off" in t or "cutoff" in t:
        return "🏆 RESULT"
    if "recruitment" in t or "vacancy" in t or "notice of" in t:
        return "💼 NEW JOB"
    return "📌 SSC UPDATE"


def post(title, link):
    text = (
        f"<b>{category(title)}</b>\n\n"
        f"{html.escape(title)}\n\n"
        f'🔗 <a href="{html.escape(link)}">Open / Download</a>'
        f"{FOOTER}"
    )
    tg("sendMessage", chat_id=CHAT_ID, text=text, parse_mode="HTML", disable_web_page_preview="true")
    if SEND_PDF_FILES and link.lower().endswith(".pdf"):
        tg("sendDocument", chat_id=CHAT_ID, document=link,
           caption="📢 Join @THEKHUNKHARSOFFICIAL")
    time.sleep(3)  # avoid Telegram flood limits


def run_once(seen, first_run):
    new_count = 0
    for src in SOURCES:
        for title, link in fetch_links(src):
            if link in seen:
                continue
            seen.add(link)
            if not first_run:       # first run only records existing links (no spam)
                post(title, link)
                new_count += 1
    save_seen(seen)
    log.info("Check done. New posts: %d", new_count)


def main():
    seen = load_seen()
    first_run = seen is None
    seen = seen or set()
    if first_run:
        log.info("First run: saving existing links without posting.")
    if os.getenv("RUN_ONCE") == "1":   # used by GitHub Actions
        run_once(seen, first_run)
        return
    while True:
        try:
            run_once(seen, first_run)
            first_run = False
        except Exception as e:
            log.exception("Loop error: %s", e)
        time.sleep(CHECK_EVERY_SECONDS)


if __name__ == "__main__":
    main()
