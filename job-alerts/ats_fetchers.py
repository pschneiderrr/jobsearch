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
