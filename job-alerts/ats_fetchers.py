"""
Общие функции получения вакансий с публичных API разных ATS + общие фильтры
(свежесть, формат работы, географическая принадлежность к нужному часовому поясу).
Используются и direct_scan.py (мониторинг шорт-листа), и search_scan.py (поиск).
"""
from datetime import datetime, timezone

import requests


def _fmt_date(value):
    """Приводит ISO-строку или epoch-timestamp (Lever отдаёт в мс) к виду YYYY-MM-DD."""
    if not value:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        except Exception:
            return None
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%Y-%m-%d")
        except Exception:
            return value[:10] if len(value) >= 10 else value
    return None


def is_recent(posted_at, max_age_days):
    """True — вакансия не старше max_age_days, или дата неизвестна (в этом случае
    не отбраковываем по свежести, чтобы не терять вакансии из-за отсутствия поля)."""
    if not posted_at:
        return True
    try:
        posted = datetime.strptime(posted_at, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return True
    return (datetime.now(timezone.utc) - posted).days <= max_age_days


SPAIN_SIGNALS = ["spain", "barcelona", "madrid", "valencia", "sevilla", "seville", "bilbao", "malaga", "málaga"]


def workplace_allowed(job):
    """True — формат работы подходит: remote где угодно, либо hybrid, если это Испания.
    On-site — никогда. Приоритет структурному полю workplace_type (есть у Ashby/Lever),
    иначе эвристика по тексту локации."""
    wt = (job.get("workplace_type") or "").strip().lower()
    loc = (job.get("location") or "").lower()
    is_spain = any(s in loc for s in SPAIN_SIGNALS)

    if wt == "remote":
        return True
    if wt == "hybrid":
        return is_spain
    if wt:
        return False

    if "hybrid" in loc:
        return is_spain
    if any(s in loc for s in ["on-site", "onsite", "in office", "in-office"]):
        return False
    if "remote" in loc:
        return True
    parts = [p.strip() for p in loc.split(",") if p.strip()]
    if len(parts) >= 3:
        return False
    return True


EUROPE_TZ_SIGNALS = [
    "europe", "emea", "remote - eu", "remote (eu)", "cet", "cest",
    "uk", "united kingdom", "england", "scotland", "wales", "london",
    "ireland", "dublin",
    "spain", "madrid", "barcelona", "portugal", "lisbon",
    "france", "paris", "belgium", "brussels", "netherlands", "amsterdam", "luxembourg",
    "germany", "berlin", "munich", "hamburg", "austria", "vienna",
    "switzerland", "zurich", "geneva",
    "sweden", "stockholm", "norway", "oslo", "denmark", "copenhagen",
    "finland", "helsinki", "iceland",
    "italy", "milan", "rome", "greece", "athens",
    "poland", "warsaw", "czech", "prague", "hungary", "budapest",
    "romania", "bucharest", "bulgaria", "sofia", "croatia", "zagreb",
    "slovakia", "slovenia", "serbia", "belgrade",
    "estonia", "tallinn", "latvia", "riga", "lithuania", "vilnius",
    "malta", "cyprus",
    "georgia", "tbilisi", "armenia", "yerevan", "azerbaijan", "baku",
    "uae", "emirates", "dubai", "abu dhabi",
    "russia", "moscow", "saint petersburg", "st. petersburg",
    "turkey", "istanbul",
]

US_OVERRIDE_SIGNALS = ["united states", " usa", "u.s.", "(us)"]


def is_european_timezone(location):
    loc = (location or "").lower()
    if any(s in loc for s in US_OVERRIDE_SIGNALS):
        return False
    return any(s in loc for s in EUROPE_TZ_SIGNALS)


def fetch_greenhouse(slug):
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    jobs = r.json().get("jobs", [])
    return [
        {
            "id": f"greenhouse:{slug}:{j['id']}",
            "title": j.get("title", ""),
            "url": j.get("absolute_url", ""),
            "location": (j.get("location") or {}).get("name", ""),
            "posted_at": _fmt_date(j.get("first_published_at") or j.get("updated_at")),
            "workplace_type": "",
        }
        for j in jobs
    ]


def fetch_lever(slug):
    url = f"https://api.lever.co/v1/postings/{slug}?mode=json"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    jobs = r.json()
    if not isinstance(jobs, list):
        raise ValueError("unexpected lever response")
    return [
        {
            "id": f"lever:{slug}:{j['id']}",
            "title": j.get("text", ""),
            "url": j.get("hostedUrl", ""),
            "location": (j.get("categories") or {}).get("location", ""),
            "posted_at": _fmt_date(j.get("createdAt")),
            "workplace_type": j.get("workplaceType", ""),
        }
        for j in jobs
    ]


def fetch_ashby(slug):
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    jobs = data.get("jobs")
    if jobs is None:
        jobs = data.get("jobPostings")
    if jobs is None:
        raise
