"""
Общие функции получения вакансий с публичных API разных ATS.
Используются и direct_scan.py (мониторинг шорт-листа), и search_scan.py
(проверка реальной локации и даты публикации вакансий, найденных через поиск).
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
