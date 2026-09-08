"""
Опрашивает Greenhouse/Lever/Ashby по компаниям из companies.json,
фильтрует по ключевым словам из keywords.json,
шлёт новые вакансии в Telegram.
Состояние (что уже видели) хранится в state/seen_direct.json и коммитится обратно в репо workflow'ом.
"""
import os
import json
import requests
from pathlib import Path

STATE_FILE = Path("state/seen_direct.json")
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
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "disable_web_page_preview": False,
        },
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


def fetch_greenhouse(slug):
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    jobs = r.json().get("jobs", [])
    return [
        {
            "id": f"greenhouse:{slug}:{j['id']}",
            "title": j.get("title", ""),
            "url": j.get("absolute_url", ""),
            "location": (j.get("location") or {}).get("name", ""),
        }
        for j in jobs
    ]


def fetch_lever(slug):
    url = f"https://api.lever.co/v1/postings/{slug}?mode=json"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    jobs = r.json()
    return [
        {
            "id": f"lever:{slug}:{j['id']}",
            "title": j.get("text", ""),
            "url": j.get("hostedUrl", ""),
            "location": (j.get("categories") or {}).get("location", ""),
        }
        for j in jobs
    ]


def fetch_ashby(slug):
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    data = r.json()
    jobs = data.get("jobs") or data.get("jobPostings") or []
    result = []
    for j in jobs:
        jid = j.get("id") or j.get("jobId")
        result.append(
            {
                "id": f"ashby:{slug}:{jid}",
                "title": j.get("title", ""),
                "url": j.get("jobUrl") or j.get("applyUrl") or "",
                "location": j.get("locationName") or j.get("location", ""),
            }
        )
    return result


FETCHERS = {"greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby}


def main():
    companies = load_json(COMPANIES_FILE, [])
    keywords = load_json(KEYWORDS_FILE, {"title_include": [], "title_exclude": []})
    seen = set(load_json(STATE_FILE, []))
    new_seen = set(seen)
    new_jobs = []

    for c in companies:
        platform = c["platform"]
        slug = c["slug"]
        name = c.get("name", slug)
        fetcher = FETCHERS.get(platform)
        if not fetcher:
            print(f"Неизвестная платформа {platform} для {name}")
            continue
        try:
            jobs = fetcher(slug)
        except Exception as e:
            print(f"Ошибка при запросе {name} ({platform}): {e}")
            continue
        for j in jobs:
            if j["id"] in seen:
                continue
            new_seen.add(j["id"])
            if matches_keywords(j["title"], keywords):
                new_jobs.append({**j, "company": name})

    for j in new_jobs:
        text = f"🎯 [шорт-лист] {j['company']}: {j['title']}\n{j['location']}\n{j['url']}"
        send_telegram(text)

    save_json(STATE_FILE, sorted(new_seen))
    print(f"Проверено компаний: {len(companies)}, новых подходящих вакансий: {len(new_jobs)}")


if __name__ == "__main__":
    main()
