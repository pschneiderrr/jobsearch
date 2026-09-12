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


# Испания (в первую очередь Барселона) — единственное исключение, где ок гибрид.
SPAIN_SIGNALS = ["spain", "barcelona", "madrid", "valencia", "sevilla", "seville", "bilbao", "malaga", "málaga"]


def workplace_allowed(job):
    """True — формат работы подходит: remote где угодно, либо hybrid, если это Испания.
    On-site — никогда. Приоритет структурному полю workplace_type (есть у Ashby/Lever),
    иначе эвристика по тексту локации (менее надёжно — так ловятся не все on-site у
    платформ без этого поля)."""
    wt = (job.get("workplace_type") or "").strip().lower()
    loc = (job.get("location") or "").lower()
    is_spain = any(s in loc for s in SPAIN_SIGNALS)

    if wt == "remote":
        return True
    if wt == "hybrid":
        return is_spain
    if wt:  # "onsite" или любое другое значение
        return False

    if "hybrid" in loc:
        return is_spain
    if any(s in loc for s in ["on-site", "onsite", "in office", "in-office"]):
        return False
    if "remote" in loc:
        return True
    parts = [p.strip() for p in loc.split(",") if p.strip()]
    if len(parts) >= 3:
        return False  # несколько городов через запятую без "remote" — похоже на мультихаб onsite
    return True  # неопределённо (например просто "London, UK") — тут не блокируем,
                 # в search_scan.py решает ещё и is_european_timezone


# Белый список: ЕС + UK + явные исключения по часовому поясу.
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
    # явные исключения по часовому поясу
    "georgia", "tbilisi", "armenia", "yerevan", "azerbaijan", "baku",
    "uae", "emirates", "dubai", "abu dhabi",
    "russia", "moscow", "saint petersburg", "st. petersburg",
    "turkey", "istanbul",
]

# Слова, при виде которых исключаем всегда, даже если что-то выше совпало по ошибке
# (пример реальной коллизии: "Georgia" — и страна на Кавказе, и штат США).
US_OVERRIDE_SIGNALS = ["united states", " usa", "u.s.", "(us)"]


def is_clearly_us(location):
    """True — только если локация ЯВНО указывает на США (без двусмысленности типа
    штата Georgia). Используется как единственный жёсткий гео-блок в search_scan.py —
    остальное пропускается, а локация/формат просто показываются в сообщении."""
    loc = (location or "").lower()
    return any(s in loc for s in US_OVERRIDE_SIGNALS)


def describe_workplace(job):
    """Текстовая метка формата работы для отображения в Telegram (не для фильтрации)."""
    wt = (job.get("workplace_type") or "").strip()
    if wt:
        return wt
    loc = (job.get("location") or "").lower()
    if "hybrid" in loc:
        return "Hybrid (по тексту локации)"
    if any(s in loc for s in ["on-site", "onsite", "in office", "in-office"]):
        return "On-site (по тексту локации)"
    if "remote" in loc:
        return "Remote (по тексту локации)"
    return "не указан"


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
        raise ValueError("unexpected ashby response")
    result = []
    for j in jobs:
        jid = j.get("id") or j.get("jobId")
        result.append(
            {
                "id": f"ashby:{slug}:{jid}",
                "title": j.get("title", ""),
                "url": j.get("jobUrl") or j.get("applyUrl") or "",
                "location": j.get("locationName") or j.get("location", ""),
                "posted_at": _fmt_date(j.get("publishedAt")),
                "workplace_type": j.get("workplaceType", ""),
            }
        )
    return result


def fetch_workable(slug):
    url = f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    jobs = data.get("jobs")
    if jobs is None:
        raise ValueError("unexpected workable response")
    result = []
    for j in jobs:
        loc = j.get("location") or {}
        place = loc.get("city") or loc.get("region") or loc.get("country") or ""
        result.append(
            {
                "id": f"workable:{slug}:{j.get('shortcode') or j.get('id')}",
                "title": j.get("title", ""),
                "url": j.get("url") or j.get("shortlink") or "",
                "location": place,
                "posted_at": _fmt_date(j.get("published_on") or j.get("created_at")),
                "workplace_type": "",
            }
        )
    return result


def fetch_recruitee(slug):
    url = f"https://{slug}.recruitee.com/api/offers/"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    offers = data.get("offers")
    if offers is None:
        raise ValueError("unexpected recruitee response")
    result = []
    for j in offers:
        parts = [j.get("city"), j.get("state"), j.get("country")]
        location = ", ".join(p for p in parts if p)
        result.append(
            {
                "id": f"recruitee:{slug}:{j.get('id')}",
                "title": j.get("title", ""),
                "url": j.get("careers_url") or j.get("careersUrl") or "",
                "location": location,
                "posted_at": _fmt_date(j.get("created_at") or j.get("createdAt") or j.get("published_at")),
                "workplace_type": "",
            }
        )
    return result


def fetch_teamtailor(slug):
    url = f"https://{slug}.teamtailor.com/jobs.json"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    jobs = data.get("jobs") if isinstance(data, dict) else data
    if jobs is None:
        raise ValueError("unexpected teamtailor response")
    result = []
    for j in jobs:
        result.append(
            {
                "id": f"teamtailor:{slug}:{j.get('id')}",
                "title": j.get("title", ""),
                "url": j.get("url") or j.get("apply_url") or "",
                "location": j.get("location") or j.get("city") or "",
                "posted_at": _fmt_date(j.get("date_published") or j.get("postedAt") or j.get("created_at")),
                "workplace_type": "",
            }
        )
    return result


FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "workable": fetch_workable,
    "recruitee": fetch_recruitee,
    "teamtailor": fetch_teamtailor,
}
