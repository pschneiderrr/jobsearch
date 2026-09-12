"""
Опрашивает Greenhouse/Lever/Ashby/Workable по компаниям из companies.json.
Если для компании не указаны platform/slug — пытается угадать их сама,
перебирая варианты написания названия по всем четырём API, и запоминает
результат в state/resolved_companies.json, чтобы не гадать заново каждый запуск.
Фильтрует по ключевым словам из keywords.json, шлёт новые вакансии в Telegram.
"""
import os
import re
import json
import requests
from pathlib import Path

from ats_fetchers import FETCHERS, workplace_allowed, is_recent

STATE_FILE = Path("state/seen_direct.json")
RESOLVED_FILE = Path("state/resolved_companies.json")
COMPANIES_FILE = Path("companies.json")
KEYWORDS_FILE = Path("keywords.json")

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]


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


def matches_keywords(title, keywords):
    t = (title or "").lower()
    inc = keywords.get("title_include", [])
    exc = keywords.get("title_exclude", [])
    if inc and not any(k.lower() in t for k in inc):
        return False
    if any(k.lower() in t for k in exc):
        return False
    return True


def slug_candidates(name):
    alt = None
    m = re.search(r"\(([^)]+)\)", name)
    base = re.sub(r"\([^)]*\)", "", name).strip()
    if m:
        alt = m.group(1).strip()

    def forms(s):
        smashed = re.sub(r"[^a-z0-9]+", "", s.lower())
        hyphen = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
        return [x for x in {smashed, hyphen} if x]

    candidates = forms(base)
    if alt:
        candidates += [c for c in forms(alt) if c not in candidates]
    return candidates


def auto_resolve(name, resolved_cache):
    if name in resolved_cache:
        return resolved_cache[name]

    for slug in slug_candidates(name):
        for platform, fetcher in FETCHERS.items():
            try:
                fetcher(slug)
            except Exception:
                continue
            match = {"platform": platform, "slug": slug}
            resolved_cache[name] = match
            print(f"Автоопределено: {name} -> {platform}:{slug} (сверь вручную — возможна коллизия имён)")
            return match

    resolved_cache[name] = None
    print(f"Не удалось определить платформу для «{name}» — впиши platform/slug вручную в companies.json")
    return None


def main():
    companies = load_json(COMPANIES_FILE, [])
    keywords = load_json(KEYWORDS_FILE, {"title_include": [], "title_exclude": []})
    max_age_days = keywords.get("max_age_days", 14)
    seen = set(load_json(STATE_FILE, []))
    resolved_cache = load_json(RESOLVED_FILE, {})
    new_seen = set(seen)
    new_jobs = []

    for c in companies:
        name = c.get("name", "")
        platform = c.get("platform") or ""
        slug = c.get("slug") or ""

        if not platform or not slug:
            match = auto_resolve(name, resolved_cache)
            if not match:
                continue
            platform, slug = match["platform"], match["slug"]

        fetcher = FETCHERS.get(platform)
        if not fetcher:
            print(f"Неизвестная платформа {platform} для {name}")
            continue
        try:
            jobs = fetcher(slug)
        except Exception as e:
            print(f"Ошибка при запросе {name} ({platform}:{slug}): {e}")
            continue
        for j in jobs:
            if j["id"] in seen:
                continue
            new_seen.add(j["id"])
            if not matches_keywords(j["title"], keywords):
                continue
            if not workplace_allowed(j):
                continue
            if not is_recent(j.get("posted_at"), max_age_days):
                continue
            new_jobs.append({**j, "company": name})

    for j in new_jobs:
        posted = j.get("posted_at") or "дата неизвестна"
        text = f"🎯 [шорт-лист] {j['company']}: {j['title']}\n{j['location']}\nОпубликовано: {posted}\n{j['url']}"
        send_telegram(text)

    save_json(STATE_FILE, sorted(new_seen))
    save_json(RESOLVED_FILE, resolved_cache)
    print(f"Проверено компаний: {len(companies)}, новых подходящих вакансий: {len(new_jobs)}")


if __name__ == "__main__":
    main()
