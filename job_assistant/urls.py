"""URL normalization for stable, duplicate-safe job tracking."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit


def canonicalize_job_url(url: str) -> str:
    """Remove transient tracking parameters and return LinkedIn's stable job URL when possible."""
    parsed = urlsplit(url.strip())
    path = parsed.path.rstrip("/")
    if is_linkedin_hostname(parsed.hostname):
        job_id = _linkedin_job_id(path, parsed.query)
        if job_id:
            return f"https://www.linkedin.com/jobs/view/{job_id}/"
    query = parse_qs(parsed.query, keep_blank_values=True)
    stable_query = {
        key: values
        for key, values in query.items()
        if not key.casefold().startswith("utm_") and key.casefold() not in {"trk", "refid", "ebp"}
    }
    return urlunsplit((parsed.scheme, parsed.netloc, path or "/", urlencode(stable_query, doseq=True), ""))


def is_linkedin_hostname(hostname: str | None) -> bool:
    """Match LinkedIn itself and its subdomains, never lookalike domains."""
    normalized = (hostname or "").casefold().rstrip(".")
    return normalized == "linkedin.com" or normalized.endswith(".linkedin.com")


def _linkedin_job_id(path: str, query: str) -> str | None:
    match = re.search(r"/jobs/view/(\d+)", path)
    if match:
        return match.group(1)
    current_job_id = parse_qs(query).get("currentJobId", [])
    return current_job_id[0] if current_job_id and current_job_id[0].isdigit() else None
