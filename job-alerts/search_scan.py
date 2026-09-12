"""
Ищет по job-board доменам через Serper.dev (обёртка над Google-поиском).

Раньше пытались жёстко фильтровать по гео/формату работы — но точное сопоставление
URL из поиска с записью в ATS API часто не срабатывает технически (реферальные
метки в ссылке, другой формат URL и т.п.), из-за чего фильтр резал не только США,
но и нормальные европейские вакансии, которые просто не удалось подтвердить.

Текущий принцип: жёстко блокируем только то, что ЯВНО и однозначно США
(is_clearly_us). Всё остальное пропускаем, добавляя в сообщение строки
с локацией и форматом работы — дальше человек решает сам, глядя на текст.
Свежесть (max_age_days) остаётся жёстким фильтром — тут суждение не нужно.

Если вакансию не удалось заново найти на текущей доске компании — это почти
всегда значит, что она уже закрыта/снята, и такая ссылка отсеивается
(а не показывается с пустыми полями).

Домены/ключевые слова/свежесть — в search_queries.json. Состояние — state/seen_search.json.
"""
import os
import re
import json
import requests
from pathlib import Path
from urllib.parse import urlparse

from ats_fetchers import FETCHERS, is_clearly_us, describe_workplace, is_recent

STATE_FILE = Path("state/seen_search.json")
QUERIES_FILE = Path("search_queries.json")

SERPER_API_KEY = os.environ["SERPER_API_KEY"]
TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

URL_PATTERNS = [
    (re.compile(r"^https?://jobs\.ashbyhq\.com/([^/]+)/"), "ashby"),
    (re.compile(r"^https?://(?:boards|job-boards)\.greenhouse\.io/([^/]+)/"), "greenhouse"),
    (re.compile(r"^https?://jobs\.lever\.co/([^/]+)/"), "lever"),
    (re.compile(r"^https?://apply\.workable\.com/([^/]+)/"), "workable"),
    (re.compile(r"^https?://([^.]+)\.recruitee\.com/"), "recruitee"),
    (re.compile(r"^https?://([^.]+)\.teamtailor\.com/"), "teamtailor"),
]


def load_json(path, default):
    if path.exists():
        return json.loads(path.read_text())
    return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        data={"chat_id": TELEGRAM_CHAT_ID, "text": text, "disable_web_page_preview": False},
        timeout=15,
    )
    if not resp.ok:
        print("Telegram error:", resp.text)


def build_queries(config):
    sites = config.get("sites", [])
    keywords = config.get("keywords", [])
    exclude = config.get("exclude", [])
    site_filter = " OR ".join(f"site:{s}" for s in sites)
    exclude_filter = " ".join(f'-"{e}"' for e in exclude)

    queries = []
    for k in keywords:
        q = f'"{k}"'
        if site_filter:
            q += f" ({site_filter})"
        if exclude_filter:
            q += f" {exclude_filter}"
        queries.append(q)
    return queries


def search(query):
    url = "https://google.serper.dev/search"
    headers = {"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"}
    r = requests.post(url, headers=headers, json={"q": query, "num": 10}, timeout=15)
    if not r.ok:
        raise RuntimeError(f"{r.status_code}: {r.text}")
    return r.json().get("organic", [])


def is_allowed_domain(url, allowed_domains):
    host = urlparse(url).netloc.lower()
    return any(host == d or host.endswith("." + d) for d in allowed_domains)


def _normalize_url(u):
    """Убирает query-параметры (реферальные метки вроде ?gh_src=...) и типовые
    суффиксы подстраниц — ссылка из поиска и URL из ATS API редко совпадают буквально."""
    if not u:
        return ""
    u = u.split("?")[0].split("#")[0]
    for suffix in ("/application", "/apply"):
        if u.endswith(suffix):
            u = u[: -len(suffix)]
