"""
Ищет по job-board доменам через Serper.dev (обёртка над Google-поиском) —
Google Custom Search JSON API закрыт для новых аккаунтов с 2025 года, для новых
проектов не работает ни при каких настройках, поэтому используем альтернативу.
Домены и ключевые слова задаются в search_queries.json.
Шлёт новые ссылки в Telegram. Состояние — state/seen_search.json.
"""
import os
import json
import requests
from pathlib import Path

STATE_FILE = Path("state/seen_search.json")
QUERIES_FILE = Path("search_queries.json")

SERPER_API_KEY = os.environ["SERPER_API_KEY"]
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


def main():
    config = load_json(QUERIES_FILE, {"sites": [], "keywords": []})
    queries = build_queries(config)
    seen = set(load_json(STATE_FILE, []))
    new_seen = set(seen)
    new_results = []

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
            new_results.append({"title": item.get("title", ""), "link": link, "query": q})

    for r in new_results:
        text = f"🔍 {r['title']}\n{r['link']}"
        send_telegram(text)

    save_json(STATE_FILE, sorted(new_seen))
    print(f"Запросов: {len(queries)}, новых результатов: {len(new_results)}")


if __name__ == "__main__":
    main()
