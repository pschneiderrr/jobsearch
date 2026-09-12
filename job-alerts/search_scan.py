"""
Ищет по job-board доменам через Serper.dev (обёртка над Google-поиском).
Фильтры поверх результатов поиска:

1. Домен ссылки — строго из списка в search_queries.json.
2. Локация — белый список (is_european_timezone в ats_fetchers.py): ЕС + UK +
   явные исключения по часовому поясу (Кавказ, Эмираты, Россия, Турция).
3. Формат работы (workplace_allowed) — только remote, кроме Испании (ок гибрид).
4. Свежесть (is_recent) — не старше max_age_days из конфига.

Домены/ключевые слова/свежесть — в search_queries.json. Состояние — state/seen_search.json.
"""
import os
import re
import json
import requests
from pathlib import Path
from urllib.parse import urlparse

from ats_fetchers import FETCHERS, is_european_timezone, workplace_allowed, is_recent

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


def find_job(url):
    """Возвращает найденный job-dict с этой платформы, или None если платформа
    не поддерживается / не удалось подтвердить (сетевая ошибка и т.п.)."""
    for pattern, platform in URL_PATTERNS:
        m = pattern.match(url)
        if not m:
            continue
        slug = m.group(1)
        try:
            jobs = FETCHERS[platform](slug)
        except Exception:
            return None
        for j in jobs:
            if j["url"] == url:
                return j
        return None
    return None


def main():
    config = load_json(QUERIES_FILE, {"sites": [], "keywords": []})
    allowed_domains = [d.lower() for d in config.get("sites", [])]
    max_age_days = config.get("max_age_days", 14)
    queries = build_queries(config)
    seen = set(load_json(STATE_FILE, []))
    new_seen = set(seen)
    new_results = []
    skipped_domain = 0
    skipped_geo = 0
    skipped_format = 0
    skipped_stale = 0

    for q in queries:
        try:
            items = search(q)
        except Exception as e:
            print(f"Ошибка запроса '{q}': {e}")
            continue
        for item in items:
            link = item.get("link")
            if not link or link in seen:
                continue
            new_seen.add(link)

            if not is_allowed_domain(link, allowed_domains):
                skipped_domain += 1
                continue

            job = find_job(link)
            if job is None or not is_european_timezone(job.get("location")):
                skipped_geo += 1
                continue
            if not workplace_allowed(job):
                skipped_format += 1
                continue
            if not is_recent(job.get("posted_at"), max_age_days):
                skipped_stale += 1
                continue

            new_results.append(
                {
                    "title": item.get("title", ""),
                    "link": link,
                    "location": job.get("location", ""),
                    "posted_at": job.get("posted_at") or "дата неизвестна",
                }
            )

    for r in new_results:
        text = (
            f"🔍 [поиск] {r['title']}\n{r['location']}\n"
            f"Опубликовано: {r['posted_at']}\n{r['link']}"
        )
        send_telegram(text)

    save_json(STATE_FILE, sorted(new_seen))
    print(
        f"Запросов: {len(queries)}, новых результатов: {len(new_results)}, "
        f"отсеяно не по домену: {skipped_domain}, отсеяно по гео: {skipped_geo}, "
        f"отсеяно по формату: {skipped_format}, отсеяно как устаревшее: {skipped_stale}"
    )


if __name__ == "__main__":
    main()
