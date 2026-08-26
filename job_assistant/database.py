from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Self

from .models import Job
from .urls import canonicalize_job_url


VALID_STATUSES = frozenset({"saved", "reviewing", "ready_for_manual_submit", "submitted_manually", "rejected", "archived"})


@dataclass(frozen=True, slots=True)
class JobEvent:
    id: int
    job_id: int
    event_type: str
    occurred_at: str
    source: str
    confirmed_by_user: bool
    details: str | None = None


class JobRepository:
    """SQLite-backed job tracker with idempotent URL storage."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._initialize()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the SQLite connection after a command or test completes."""
        self.connection.close()

    def _initialize(self) -> None:
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                linkedin_job_id TEXT,
                company_url TEXT,
                application_url TEXT,
                application_method TEXT,
                location TEXT,
                salary TEXT,
                platform TEXT,
                source TEXT NOT NULL DEFAULT 'linkedin',
                job_description TEXT,
                workplace_type TEXT,
                employment_type TEXT,
                seniority_level TEXT,
                applicant_count TEXT,
                posting_date TEXT,
                description_hash TEXT,
                first_seen_at TEXT,
                last_seen_at TEXT,
                seen_count INTEGER NOT NULL DEFAULT 1,
                matching_skills TEXT,
                missing_skills TEXT,
                match_reason TEXT,
                recommendation TEXT,
                tailored_resume_path TEXT,
                follow_up_date TEXT,
                date_found TEXT NOT NULL,
                match_score INTEGER CHECK(match_score BETWEEN 0 AND 100),
                notes TEXT,
                status TEXT NOT NULL DEFAULT 'saved',
                priority TEXT,
                interest_level TEXT,
                tags TEXT,
                applied INTEGER NOT NULL DEFAULT 0 CHECK(applied IN (0, 1)),
                applied_at TEXT,
                submission_approved_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        existing_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(jobs)")}
        migrations = {
            "job_description": "TEXT",
            "workplace_type": "TEXT",
            "employment_type": "TEXT",
            "seniority_level": "TEXT",
            "applicant_count": "TEXT",
            "posting_date": "TEXT",
            "linkedin_job_id": "TEXT",
            "company_url": "TEXT",
            "application_url": "TEXT",
            "application_method": "TEXT",
            "description_hash": "TEXT",
            "first_seen_at": "TEXT",
            "last_seen_at": "TEXT",
            "seen_count": "INTEGER NOT NULL DEFAULT 1",
            "matching_skills": "TEXT",
            "missing_skills": "TEXT",
            "match_reason": "TEXT",
            "recommendation": "TEXT",
            "tailored_resume_path": "TEXT",
            "platform": "TEXT",
            "source": "TEXT NOT NULL DEFAULT 'linkedin'",
            "follow_up_date": "TEXT",
            "priority": "TEXT",
            "interest_level": "TEXT",
            "tags": "TEXT",
            "applied": "INTEGER NOT NULL DEFAULT 0",
            "applied_at": "TEXT",
        }
        for name, definition in migrations.items():
            if name not in existing_columns:
                self.connection.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS job_events (
                id INTEGER PRIMARY KEY,
                job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                event_type TEXT NOT NULL,
                occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                source TEXT NOT NULL,
                confirmed_by_user INTEGER NOT NULL DEFAULT 0 CHECK(confirmed_by_user IN (0, 1)),
                details TEXT
            )
            """
        )
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_job_events_job_time ON job_events(job_id, occurred_at)")
        self.connection.execute(
            """UPDATE jobs SET
               first_seen_at=COALESCE(first_seen_at, created_at),
               last_seen_at=COALESCE(last_seen_at, updated_at, created_at),
               seen_count=CASE WHEN seen_count IS NULL OR seen_count < 1 THEN 1 ELSE seen_count END,
               applied=CASE WHEN status='submitted_manually' THEN 1 ELSE COALESCE(applied, 0) END,
               applied_at=CASE WHEN status='submitted_manually' THEN COALESCE(applied_at, submission_approved_at, updated_at) ELSE applied_at END,
               source=COALESCE(NULLIF(TRIM(source), ''), 'linkedin')
               WHERE first_seen_at IS NULL OR last_seen_at IS NULL OR seen_count IS NULL OR seen_count < 1
                  OR applied IS NULL OR source IS NULL OR TRIM(source) = ''
                  OR (status='submitted_manually' AND (applied <> 1 OR applied_at IS NULL))"""
        )
        self._canonicalize_existing_urls()
        self.connection.commit()

    def _canonicalize_existing_urls(self) -> None:
        """Consolidate rows that differ only by tracking parameters, retaining the earliest record."""
        rows = self.connection.execute("SELECT id, url FROM jobs ORDER BY id").fetchall()
        retained_ids: dict[str, int] = {}
        duplicate_ids: list[int] = []
        changed_urls: list[tuple[str, int]] = []
        for row in rows:
            canonical_url = canonicalize_job_url(row["url"])
            if canonical_url in retained_ids:
                duplicate_ids.append(row["id"])
                continue
            retained_ids[canonical_url] = row["id"]
            if canonical_url != row["url"]:
                changed_urls.append((canonical_url, row["id"]))
        if duplicate_ids:
            self.connection.executemany("DELETE FROM jobs WHERE id = ?", [(job_id,) for job_id in duplicate_ids])
        if changed_urls:
            self.connection.executemany("UPDATE jobs SET url = ? WHERE id = ?", changed_urls)

    def upsert(self, job: Job) -> Job:
        job.url = canonicalize_job_url(job.url)
        existing = self.by_url(job.url)
        self.connection.execute(
            """
            INSERT INTO jobs (
              title, company, url, linkedin_job_id, company_url, application_url, application_method,
              location, salary, platform, source, job_description, workplace_type, employment_type, seniority_level,
              applicant_count, posting_date, description_hash, first_seen_at, last_seen_at, seen_count,
              date_found, match_score, notes, status, priority, interest_level, tags, applied, applied_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
              title=excluded.title, company=excluded.company, location=COALESCE(excluded.location, jobs.location),
              salary=COALESCE(excluded.salary, jobs.salary), match_score=COALESCE(excluded.match_score, jobs.match_score),
              platform=COALESCE(excluded.platform, jobs.platform), source=excluded.source,
              linkedin_job_id=COALESCE(excluded.linkedin_job_id, jobs.linkedin_job_id),
              company_url=COALESCE(excluded.company_url, jobs.company_url),
              application_url=COALESCE(excluded.application_url, jobs.application_url),
              application_method=COALESCE(excluded.application_method, jobs.application_method),
              job_description=COALESCE(excluded.job_description, jobs.job_description),
              workplace_type=COALESCE(excluded.workplace_type, jobs.workplace_type),
              employment_type=COALESCE(excluded.employment_type, jobs.employment_type),
              seniority_level=COALESCE(excluded.seniority_level, jobs.seniority_level),
              applicant_count=COALESCE(excluded.applicant_count, jobs.applicant_count),
              posting_date=COALESCE(excluded.posting_date, jobs.posting_date),
              description_hash=COALESCE(excluded.description_hash, jobs.description_hash),
              last_seen_at=COALESCE(excluded.last_seen_at, CURRENT_TIMESTAMP),
              seen_count=jobs.seen_count + 1,
              notes=COALESCE(excluded.notes, jobs.notes), updated_at=CURRENT_TIMESTAMP
            """,
            (
                job.title, job.company, job.url, job.linkedin_job_id, job.company_url, job.application_url,
                job.application_method, job.location, job.salary, job.platform, job.source, job.job_description,
                job.workplace_type, job.employment_type, job.seniority_level, job.applicant_count,
                job.posting_date, job.description_hash, job.first_seen_at, job.last_seen_at, job.seen_count,
                job.date_found, job.match_score, job.notes, job.status, job.priority, job.interest_level,
                job.tags, int(job.applied), job.applied_at,
            ),
        )
        saved = self.by_url(job.url)
        assert saved is not None
        if existing is None:
            self._record_event(_job_id(saved), "CAPTURED", source="extension", confirmed_by_user=False)
        self.connection.commit()
        return saved

    def get(self, job_id: int) -> Job | None:
        row = self.connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    def by_url(self, url: str) -> Job | None:
        row = self.connection.execute("SELECT * FROM jobs WHERE url = ?", (canonicalize_job_url(url),)).fetchone()
        return self._row_to_job(row) if row else None

    def list(self, status: str | None = None) -> list[Job]:
        query, params = "SELECT * FROM jobs", ()
        if status:
            query, params = f"{query} WHERE status = ?", (status,)
        rows = self.connection.execute(f"{query} ORDER BY date_found DESC, id DESC", params).fetchall()
        return [self._row_to_job(row) for row in rows]

    def update(self, job_id: int, *, score: int | None, notes: str | None, status: str | None, follow_up_date: str | None = None) -> Job:
        job = self.get(job_id)
        if not job:
            raise KeyError(f"No job found with id {job_id}.")
        if score is not None and not 0 <= score <= 100:
            raise ValueError("Match score must be between 0 and 100.")
        if status and status not in VALID_STATUSES:
            raise ValueError(f"Invalid status. Choose from: {', '.join(sorted(VALID_STATUSES))}")
        if follow_up_date:
            try:
                date.fromisoformat(follow_up_date)
            except ValueError as exc:
                raise ValueError("Follow-up date must use YYYY-MM-DD.") from exc
        self.connection.execute(
            """UPDATE jobs SET match_score=COALESCE(?, match_score), notes=COALESCE(?, notes),
               status=COALESCE(?, status), follow_up_date=COALESCE(?, follow_up_date), updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (score, notes, status, follow_up_date, job_id),
        )
        self.connection.commit()
        return self._required_job(job_id)

    def record_submission_approval(self, job_id: int) -> Job:
        job = self.get(job_id)
        if not job:
            raise KeyError(f"No job found with id {job_id}.")
        self.connection.execute(
            """UPDATE jobs SET status='ready_for_manual_submit', submission_approved_at=CURRENT_TIMESTAMP,
               updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (job_id,),
        )
        self.connection.commit()
        return self._required_job(job_id)

    def set_applied(self, job_id: int, applied: bool) -> Job:
        """Set the user-confirmed application state and retain an auditable event."""
        job = self.get(job_id)
        if not job:
            raise KeyError(f"No job found with id {job_id}.")
        if job.applied == applied:
            return job
        if applied:
            self.connection.execute(
                """UPDATE jobs SET applied=1, applied_at=CURRENT_TIMESTAMP, status='submitted_manually',
                   updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (job_id,),
            )
            event_type = "APPLICATION_SUBMITTED"
        else:
            self.connection.execute(
                """UPDATE jobs SET applied=0, applied_at=NULL,
                   status=CASE WHEN status='submitted_manually' THEN 'saved' ELSE status END,
                   updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (job_id,),
            )
            event_type = "APPLICATION_UNMARKED"
        self._record_event(job_id, event_type, source="dashboard", confirmed_by_user=True)
        self.connection.commit()
        return self._required_job(job_id)

    def events(self, job_id: int) -> list[JobEvent]:
        rows = self.connection.execute(
            "SELECT * FROM job_events WHERE job_id=? ORDER BY occurred_at, id",
            (job_id,),
        ).fetchall()
        return [
            JobEvent(
                id=row["id"],
                job_id=row["job_id"],
                event_type=row["event_type"],
                occurred_at=row["occurred_at"],
                source=row["source"],
                confirmed_by_user=bool(row["confirmed_by_user"]),
                details=row["details"],
            )
            for row in rows
        ]

    def save_match(self, job_id: int, *, score: int, matching_skills: str, missing_skills: str, reason: str, recommendation: str) -> Job:
        job = self.get(job_id)
        if not job:
            raise KeyError(f"No job found with id {job_id}.")
        self.connection.execute(
            """UPDATE jobs SET match_score=?, matching_skills=?, missing_skills=?, match_reason=?, recommendation=?,
               updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (score, matching_skills, missing_skills, reason, recommendation, job_id),
        )
        self.connection.commit()
        return self._required_job(job_id)

    def reset_match(self, job_id: int) -> Job:
        """Clear stale analysis after the visible job description is captured again."""
        job = self.get(job_id)
        if not job:
            raise KeyError(f"No job found with id {job_id}.")
        self.connection.execute(
            """UPDATE jobs SET match_score=NULL, matching_skills=NULL, missing_skills=NULL,
               match_reason='Resume comparison is queued and will update automatically.',
               recommendation='analysis pending', tailored_resume_path=NULL,
               updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (job_id,),
        )
        self.connection.commit()
        return self._required_job(job_id)

    def set_tailored_resume_path(self, job_id: int, path: str | None) -> Job:
        """Record the locally generated PDF associated with a current match result."""
        job = self.get(job_id)
        if not job:
            raise KeyError(f"No job found with id {job_id}.")
        self.connection.execute(
            "UPDATE jobs SET tailored_resume_path=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (path, job_id),
        )
        self.connection.commit()
        return self._required_job(job_id)

    def mark_analysis_error(self, job_id: int, message: str) -> None:
        """Expose a background-analysis failure on its saved job."""
        self.connection.execute(
            """UPDATE jobs SET match_reason=?, recommendation='review manually',
               updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (f"Automatic resume analysis needs attention: {message}", job_id),
        )
        self.connection.commit()

    def delete(self, job_id: int) -> None:
        """Delete one saved job while retaining not-found validation."""
        if not self.get(job_id):
            raise KeyError(f"No saved job found with id {job_id}.")
        self.connection.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        self.connection.commit()

    def delete_all(self) -> int:
        """Delete every saved job record and return the number of removed rows."""
        count = self.connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        self.connection.execute("DELETE FROM jobs")
        self.connection.commit()
        return int(count)

    def _record_event(self, job_id: int, event_type: str, *, source: str, confirmed_by_user: bool, details: str | None = None) -> None:
        self.connection.execute(
            """INSERT INTO job_events (job_id, event_type, source, confirmed_by_user, details)
               VALUES (?, ?, ?, ?, ?)""",
            (job_id, event_type, source, int(confirmed_by_user), details),
        )

    def _required_job(self, job_id: int) -> Job:
        job = self.get(job_id)
        if not job:
            raise RuntimeError(f"Job #{job_id} disappeared during update.")
        return job

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> Job:
        row_keys = set(row.keys())
        values = {key: row[key] for key in Job.__dataclass_fields__ if key in row_keys}
        if "applied" in values:
            values["applied"] = bool(values["applied"])
        return Job(**values)


def _job_id(job: Job) -> int:
    if job.id is None:
        raise RuntimeError("The saved job does not have an identifier.")
    return job.id
