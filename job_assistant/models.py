from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .urls import canonicalize_job_url


@dataclass(slots=True)
class Job:
    title: str
    company: str
    url: str
    linkedin_job_id: str | None = None
    company_url: str | None = None
    application_url: str | None = None
    application_method: str | None = None
    location: str | None = None
    salary: str | None = None
    platform: str | None = None
    job_description: str | None = None
    workplace_type: str | None = None
    employment_type: str | None = None
    seniority_level: str | None = None
    applicant_count: str | None = None
    posting_date: str | None = None
    description_hash: str | None = None
    first_seen_at: str | None = None
    last_seen_at: str | None = None
    seen_count: int = 1
    matching_skills: str | None = None
    missing_skills: str | None = None
    match_reason: str | None = None
    recommendation: str | None = None
    tailored_resume_path: str | None = None
    follow_up_date: str | None = None
    followed_up: bool = False
    followed_up_at: str | None = None
    date_found: str = ""
    match_score: int | None = None
    notes: str | None = None
    status: str = "saved"
    priority: str | None = None
    interest_level: str | None = None
    tags: str | None = None
    applied: bool = False
    applied_at: str | None = None
    id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None
    source: str = "linkedin"

    def __post_init__(self) -> None:
        self.url = canonicalize_job_url(self.url)
        if not self.date_found:
            self.date_found = datetime.now().astimezone().date().isoformat()
        if not self.title.strip() or not self.company.strip() or not self.url.strip():
            raise ValueError("Job title, company, and URL are required.")
        if self.match_score is not None and not 0 <= self.match_score <= 100:
            raise ValueError("Match score must be between 0 and 100.")
        if self.seen_count < 1:
            raise ValueError("Seen count must be at least one.")
