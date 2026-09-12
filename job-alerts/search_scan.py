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
всегда значит, что она уже закрыта/снята, и такая ссылка отсеивается.

Google ранжирует выдачу по релевантности, а не по дате — поэтому запрос
ограничен последним месяцем (tbs=qdr:m), а внутри одного прогона результаты
сортируются по дате публикации (свежее — первым).

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
    # tbs=qdr:m — ограничивает выдачу Google последним месяцем, иначе Google ранжирует
    # по релевантности/популярности, а не по дате, и свежие вакансии тонут в топ-10.
    r = requests.post(url, headers=headers, json={"q": query, "num": 10, "tbs": "qdr:m"}, timeout=15)
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
    return u.rstrip("/")


def _extract_code(u):
    """Последний сегмент пути URL — обычно это ID/shortcode вакансии.
    Используется как запасной способ сопоставления, когда ATS отдаёт
    ссылку на вакансию в другом формате, чем та, что нашёл поиск."""
    path = urlparse(u).path.rstrip("/")
    return path.rsplit("/", 1)[-1] if path else ""


def find_job(url):
    """Возвращает найденный job-dict с этой платформы, или None если платформа
    не поддерживается / вакансия уже закрыта / не удалось подтвердить.
    Сначала пробуем точное совпадение URL, если не вышло — совпадение по ID
    (устойчивее: некоторые ATS отдают ссылку в другом формате, чем в поиске)."""
    target = _normalize_url(url)
    target_code = _extract_code(target)
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
            if _normalize_url(j["url"]) == target:
                return j
        if target_code:
            for j in jobs:
                job_code = j["id"].split(":")[-1]
                if job_code and (job_code == target_code or job_code in target_code or target_code in job_code):
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
    skipped_unreachable = 0
    skipped_us = 0
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
            if job is None:
                # не нашли эту вакансию заново на текущей доске компании —
                # почти наверняка она уже закрыта/снята, ссылка мёртвая
                skipped_unreachable += 1
                continue

            location = job.get("location") or ""
            if is_clearly_us(location):
                skipped_us += 1
                continue

            posted_at = job.get("posted_at")
            if not is_recent(posted_at, max_age_days):
                skipped_stale += 1
                continue

            new_results.append(
                {
                    "title": item.get("title", ""),
                    "link": link,
                    "location": location or "неизвестна",
                    "workplace": describe_workplace(job),
                    "posted_at": posted_at or "дата неизвестна",
                }
            )

    # свежее — вперёд; неизвестная дата уходит в конец списка
    new_results.sort(key=lambda r: r["posted_at"] if r["posted_at"] != "дата неизвестна" else "0000-00-00", reverse=True)

    for r in new_results:
        text = (
            f"🔍 [поиск] {r['title']}\n"
            f"Локация: {r['location']}\n"
            f"Формат: {r['workplace']}\n"
            f"Опубликовано: {r['posted_at']}\n"
            f"{r['link']}"
        )
        send_telegram(text)

    save_json(STATE_FILE, sorted(new_seen))
    print(
        f"Запросов: {len(queries)}, новых результатов: {len(new_results)}, "
        f"отсеяно не по домену: {skipped_domain}, отсеяно как недостижимые/закрытые: {skipped_unreachable}, "
        f"отсеяно как явный US: {skipped_us}, отсеяно как устаревшее: {skipped_stale}",
        flush=True,
    )


if __name__ == "__main__":
    main()
