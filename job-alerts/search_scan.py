"""
Ищет по jobs.ashbyhq.com / boards.greenhouse.io / jobs.lever.co через Google Custom Search API
(домены ограничены в самом CSE, тут только ключевые слова).
Шлёт новые ссылки в Telegram. Состояние — state/seen_search.json.
"""
import os
import json
import requests
from pathlib import Path

STATE_FILE = Path("state/seen_search.json")
QUERIES_FILE = Path("search_queries.json")

GOOGLE_API_KEY = os.environ["GOOGLE_API_KEY"]
GOOGLE_CSE_ID = os.environ["GOOGLE_CSE_ID"]
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


def search(query):
    url = "https://www.googleapis.com/customsearch/v1"
    params = {"key": GOOGLE_API_KEY, "cx": GOOGLE_CSE_ID, "q": query, "num": 10}
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    return r.json().get("items", [])


def main():
    queries = load_json(QUERIES_FILE, {"queries": []}).get("queries", [])
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
        text = f"🔍 [поиск] {r['title']}\n{r['link']}"
        send_telegram(text)

    save_json(STATE_FILE, sorted(new_seen))
    print(f"Запросов: {len(queries)}, новых результатов: {len(new_results)}")


if __name__ == "__main__":
    main()
