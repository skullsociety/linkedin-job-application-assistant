"""Local storage, resume analysis, and dashboard for the LinkedIn extension.

The service listens only on this computer.  It is intentionally separate from
the Chrome extension: Chrome reads the page you opened, while Python retains
the existing local SQLite, resume, PDF, and Excel workflow.
"""

from __future__ import annotations

import hashlib
import html
import json
import queue
import re
import shutil
import threading
from dataclasses import asdict
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from job_assistant.config import Settings, get_settings
from job_assistant.cover_letter import generate_cover_letter
from job_assistant.database import JobRepository
from job_assistant.draft_answers import generate_draft_answers
from job_assistant.exporter import export_jobs
from job_assistant.models import Job
from job_assistant.profile import load_profile
from job_assistant.resume_matcher import extract_skills, match_resume_to_job
from job_assistant.resume_reader import latest_resume, read_resume
from job_assistant.tailored_resume import create_tailored_resume
from job_assistant.urls import canonicalize_job_url, is_linkedin_hostname

HOST = "127.0.0.1"
PORT = 8766
MAX_REQUEST_BYTES = 1_000_000
CHROME_EXTENSION_ORIGIN = "chrome-extension://kbgmahagnbefnlfjghabpfagaknmbfjd"
VERIFICATION_MARKERS = (
    "security verification",
    "verify your identity",
    "unusual activity",
    "captcha",
    "robot check",
)
INVALID_JOB_TITLES = frozenset({
    "applicant insights",
    "be among the first applicants",
    "be among the top applicants",
    "job search",
    "jobs",
    "recommended jobs",
    "top applicant",
    "you d be a top applicant",
    "you re a top applicant",
})


class LinkedInStore:
    """Thread-safe facade that opens a short-lived SQLite connection per action."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._export_lock = threading.Lock()
        # Finish schema upgrades before the health endpoint can report ready.
        with self._repository():
            pass

    def _repository(self) -> JobRepository:
        return JobRepository(self.settings.database_path)

    def upsert_capture(self, payload: dict[str, Any]) -> Job:
        job = payload_to_job(payload)
        with self._repository() as repository:
            saved = repository.upsert(job)
            # A re-capture must not show a score for an older description while
            # the current description is being analysed in the background.
            return repository.reset_match(_job_id(saved))

    def get(self, job_id: int) -> Job:
        with self._repository() as repository:
            job = repository.get(job_id)
        if not job:
            raise KeyError(f"No saved job found with id {job_id}.")
        return job

    def list(self) -> list[Job]:
        with self._repository() as repository:
            return repository.list()

    def save_analysis(self, job_id: int, *, score: int, matching: str, missing: str, reason: str, recommendation: str) -> Job:
        with self._repository() as repository:
            return repository.save_match(
                job_id,
                score=score,
                matching_skills=matching,
                missing_skills=missing,
                reason=reason,
                recommendation=recommendation,
            )

    def set_applied(self, job_id: int, applied: bool) -> Job:
        with self._repository() as repository:
            return repository.set_applied(job_id, applied)

    def set_followed_up(self, job_id: int, followed_up: bool) -> Job:
        with self._repository() as repository:
            return repository.set_followed_up(job_id, followed_up)

    def set_tailored_resume(self, job_id: int, path: str | None) -> Job:
        with self._repository() as repository:
            return repository.set_tailored_resume_path(job_id, path)

    def mark_analysis_error(self, job_id: int, message: str) -> None:
        """Make a local resume/PDF failure visible instead of leaving a job pending forever."""
        with self._repository() as repository:
            repository.mark_analysis_error(job_id, message)

    def delete(self, job_id: int) -> None:
        with self._repository() as repository:
            repository.delete(job_id)

    def clear(self) -> int:
        with self._repository() as repository:
            return repository.delete_all()

    def export(self) -> str | None:
        """Overwrite the one tracker file; an open Excel workbook never loses a capture."""
        with self._export_lock:
            try:
                with self._repository() as repository:
                    export_jobs(repository.list(), self.settings.export_path)
            except OSError as exc:
                message = str(exc)
                print(f"Excel tracker was not refreshed: {message}")
                return message
        return None

    def delete_outputs(self) -> int:
        """Remove generated output only; never remove the resume, profile, or browser session."""
        removed = 0
        if self.settings.export_path.is_file():
            self.settings.export_path.unlink()
            removed += 1
        if self.settings.tailored_resume_dir.is_dir():
            removed += sum(1 for path in self.settings.tailored_resume_dir.rglob("*") if path.is_file())
            shutil.rmtree(self.settings.tailored_resume_dir)
        return removed


class BackgroundProcessor:
    """Match and export after the page capture has already been acknowledged."""

    def __init__(self, store: LinkedInStore) -> None:
        self.store = store
        self._queue: queue.Queue[int | None] = queue.Queue()
        self._stopped = threading.Event()
        self._worker = threading.Thread(target=self._run, name="linkedin-analysis", daemon=True)
        self._worker.start()

    def enqueue(self, job_id: int) -> None:
        self._queue.put(job_id)

    def enqueue_all(self) -> int:
        jobs = self.store.list()
        for job in jobs:
            self.enqueue(_job_id(job))
        return len(jobs)

    def close(self) -> None:
        self._stopped.set()
        self._queue.put(None)
        self._worker.join(timeout=3)

    def _run(self) -> None:
        while not self._stopped.is_set():
            job_id = self._queue.get()
            if job_id is None:
                return
            try:
                self._analyse(job_id)
            except Exception as exc:  # Keep subsequent jobs moving after one bad PDF or page capture.
                print(f"Analysis for LinkedIn job #{job_id} did not finish: {exc}")
                self.store.mark_analysis_error(job_id, str(exc))
                self.store.export()
            finally:
                self._queue.task_done()

    def _analyse(self, job_id: int) -> None:
        job = self.store.get(job_id)
        if not job.job_description:
            return
        resume_path = configured_resume(self.store.settings)
        resume_text = read_resume(resume_path)
        result = match_resume_to_job(resume_text, job)
        saved = self.store.save_analysis(
            job_id,
            score=result.score,
            matching=", ".join(result.matching_skills),
            missing=", ".join(result.missing_skills),
            reason=result.reason,
            recommendation=result.recommendation,
        )
        if result.score >= self.store.settings.tailored_resume_threshold:
            output = create_tailored_resume(resume_text, saved, result, self.store.settings.tailored_resume_dir)
            self.store.set_tailored_resume(job_id, output.name)
            print(f"LinkedIn job #{job_id}: {result.score}% match; tailored resume created: {output.name}")
        else:
            self.store.set_tailored_resume(job_id, None)
            print(f"LinkedIn job #{job_id}: {result.score}% match; review recommendation: {result.recommendation}.")
        self.store.export()


def payload_to_job(payload: dict[str, Any]) -> Job:
    """Validate an extension capture without accepting page HTML or credentials."""
    if not isinstance(payload, dict):
        raise ValueError("The captured job must be an object.")
    title = _job_title(payload.get("title"))
    company = _text(payload.get("company"), "Company")
    url = canonicalize_job_url(_text(payload.get("url"), "Job URL"))
    parsed = urlsplit(url)
    if not is_linkedin_hostname(parsed.hostname) or "/jobs/view/" not in parsed.path:
        raise ValueError("Open a full LinkedIn job listing before capturing.")
    description = _optional_text(payload.get("job_description"))
    if not description:
        raise ValueError("Open and expand About the job before capturing so the visible description can be stored.")
    if len(description) > 250_000:
        raise ValueError("The visible job description is too large to store.")
    if any(marker in description.casefold() for marker in VERIFICATION_MARKERS):
        raise ValueError("LinkedIn is asking for verification. Complete it manually; this assistant will not interact with it.")
    job_id_match = re.fullmatch(r"/jobs/view/(\d+)/?", parsed.path)
    if not job_id_match:
        raise ValueError("The captured LinkedIn URL does not contain a stable job identifier.")
    linkedin_job_id = job_id_match.group(1)
    supplied_job_id = _optional_text(payload.get("linkedin_job_id"))
    if supplied_job_id and supplied_job_id != linkedin_job_id:
        raise ValueError("The captured LinkedIn job identifier does not match its URL.")
    skills = extract_skills(description)
    notes = "\n\n".join((
        f"Skills mentioned: {', '.join(skills) if skills else 'None recognized from the visible description.'}",
        f"Job description: {description}",
    ))
    captured_at = datetime.now().astimezone().isoformat(timespec="seconds")
    return Job(
        title=title,
        company=company,
        url=url,
        linkedin_job_id=linkedin_job_id,
        company_url=_optional_http_url(payload.get("company_url"), "Company URL", linkedin_only=True),
        application_url=_optional_http_url(payload.get("application_url"), "Application URL"),
        application_method=_optional_text(payload.get("application_method")),
        platform="LinkedIn",
        source="linkedin",
        location=_optional_text(payload.get("location")),
        salary=_optional_text(payload.get("salary")),
        workplace_type=_optional_text(payload.get("workplace_type")),
        employment_type=_optional_text(payload.get("employment_type")),
        seniority_level=_optional_text(payload.get("seniority_level")),
        applicant_count=_optional_text(payload.get("applicant_count")),
        posting_date=_optional_text(payload.get("posting_date")),
        job_description=description,
        description_hash=hashlib.sha256(description.encode("utf-8")).hexdigest(),
        first_seen_at=captured_at,
        last_seen_at=captured_at,
        notes=notes,
    )


def _text(value: Any, label: str) -> str:
    cleaned = _optional_text(value)
    if not cleaned:
        raise ValueError(f"{label} is not visible yet. Open a fully loaded LinkedIn job-detail page and try again.")
    return cleaned


def _job_title(value: Any) -> str:
    title = _text(value, "Job title")
    normalized = re.sub(r"[^a-z0-9]+", " ", title.casefold()).strip()
    if not any(character.isalnum() for character in title) or normalized in INVALID_JOB_TITLES:
        raise ValueError("The LinkedIn job title is not ready yet. Wait for the selected listing to finish loading and try again.")
    return title


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Captured fields must be text.")
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned or None


def _optional_http_url(value: Any, label: str, *, linkedin_only: bool = False) -> str | None:
    cleaned = _optional_text(value)
    if not cleaned:
        return None
    parsed = urlsplit(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{label} must be an HTTP or HTTPS address.")
    if linkedin_only and not is_linkedin_hostname(parsed.hostname):
        raise ValueError(f"{label} must be a LinkedIn address.")
    return cleaned


def _job_id(job: Job) -> int:
    if job.id is None:
        raise RuntimeError("The saved job does not have an identifier.")
    return job.id


def configured_resume(settings: Settings) -> Path:
    """Use the newest resume folder item, retaining the existing optional fallback."""
    try:
        return latest_resume(settings.resume_dir)
    except (FileNotFoundError, ValueError):
        if settings.resume_path and settings.resume_path.is_file():
            return settings.resume_path
        raise


def serialize_job(job: Job) -> dict[str, Any]:
    """Return only tracker information needed by the extension and dashboard."""
    data = asdict(job)
    if job.tailored_resume_path:
        data["tailored_resume_url"] = f"/tailored/{job.tailored_resume_path}"
    else:
        data["tailored_resume_url"] = None
    return data


def _revision(jobs: list[Job]) -> str:
    values = [serialize_job(job) for job in jobs]
    raw = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class CompanionHandler(BaseHTTPRequestHandler):
    """Minimal, origin-checked HTTP API used by the private extension and dashboard."""

    store: LinkedInStore
    processor: BackgroundProcessor

    def do_OPTIONS(self) -> None:  # noqa: N802 - standard library handler hook
        origin = self.headers.get("Origin", "")
        if not _is_extension_origin(origin):
            self._json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "Only the installed Chrome extension may use this endpoint."})
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors_headers(origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802 - standard library handler hook
        origin = self.headers.get("Origin", "")
        if self.path == "/":
            self._html(render_dashboard(self.store.list()))
            return
        if self.path == "/api/health":
            self._json(HTTPStatus.OK, {"ok": True, "service": "LinkedIn Job Application Assistant"}, origin)
            return
        if self.path == "/api/jobs":
            jobs = self.store.list()
            self._json(HTTPStatus.OK, {"ok": True, "jobs": [serialize_job(job) for job in jobs], "revision": _revision(jobs)}, origin)
            return
        if self.path.startswith("/api/jobs/") and self.path.removeprefix("/api/jobs/").isdigit():
            try:
                self._json(HTTPStatus.OK, {"ok": True, "job": serialize_job(self.store.get(int(self.path.rsplit("/", 1)[-1])))}, origin)
            except KeyError as exc:
                self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": str(exc)}, origin)
            return
        if self.path == "/api/profile":
            if not _is_extension_origin(origin):
                self._json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "Only the installed Chrome extension may read the safe local profile."})
                return
            try:
                profile = load_profile(self.store.settings.profile_path)
            except FileNotFoundError:
                profile = {}
            self._json(HTTPStatus.OK, {"ok": True, "profile": profile}, origin)
            return
        if self.path.startswith("/tailored/"):
            self._tailored_resume(self.path.removeprefix("/tailored/"))
            return
        self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Unknown endpoint."}, origin)

    def do_POST(self) -> None:  # noqa: N802 - standard library handler hook
        origin = self.headers.get("Origin", "")
        if not _is_extension_origin(origin) and not _is_dashboard_origin(origin):
            self._json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "This local service only accepts requests from its extension or dashboard."})
            return
        try:
            payload = self._payload()
            if self.path == "/api/jobs":
                if not _is_extension_origin(origin):
                    raise PermissionError("Only the Chrome extension may capture a job.")
                saved = self.store.upsert_capture(payload)
                warning = self.store.export()
                self.processor.enqueue(_job_id(saved))
                response: dict[str, Any] = {"ok": True, "job": serialize_job(saved), "analysis_queued": True}
                if warning:
                    response["excel_warning"] = warning
                self._json(HTTPStatus.OK, response, origin)
                return
            if self.path == "/api/jobs/rematch":
                if not _is_extension_origin(origin) and not _is_dashboard_origin(origin):
                    raise PermissionError("Only the Chrome extension or local dashboard may request resume matching.")
                count = self.processor.enqueue_all()
                self._json(HTTPStatus.OK, {"ok": True, "queued": count}, origin)
                return
            if self.path == "/api/jobs/clear":
                if not _is_dashboard_origin(origin) or payload.get("confirmation") != "DELETE":
                    raise PermissionError("Type DELETE in the local dashboard before clearing saved data.")
                removed_jobs = self.store.clear()
                removed_outputs = self.store.delete_outputs()
                self._json(HTTPStatus.OK, {"ok": True, "removed_jobs": removed_jobs, "removed_outputs": removed_outputs})
                return
            application_match = re.fullmatch(r"/api/jobs/(\d+)/application", self.path)
            if application_match:
                if not _is_dashboard_origin(origin):
                    raise PermissionError("Application status can only be changed from the local dashboard.")
                applied = payload.get("applied")
                if not isinstance(applied, bool):
                    raise ValueError("Applied must be true or false.")
                saved = self.store.set_applied(int(application_match.group(1)), applied)
                warning = self.store.export()
                response = {"ok": True, "job": serialize_job(saved)}
                if warning:
                    response["excel_warning"] = warning
                self._json(HTTPStatus.OK, response, origin)
                return
            follow_up_match = re.fullmatch(r"/api/jobs/(\d+)/follow-up", self.path)
            if follow_up_match:
                if not _is_dashboard_origin(origin):
                    raise PermissionError("Follow-up status can only be changed from the local dashboard.")
                followed_up = payload.get("followed_up")
                if not isinstance(followed_up, bool):
                    raise ValueError("Followed up must be true or false.")
                saved = self.store.set_followed_up(int(follow_up_match.group(1)), followed_up)
                warning = self.store.export()
                response = {"ok": True, "job": serialize_job(saved)}
                if warning:
                    response["excel_warning"] = warning
                self._json(HTTPStatus.OK, response, origin)
                return
            match = re.fullmatch(r"/api/jobs/(\d+)/(drafts|cover-letter)", self.path)
            if match and _is_extension_origin(origin):
                job = self.store.get(int(match.group(1)))
                resume = read_resume(configured_resume(self.store.settings))
                if match.group(2) == "cover-letter":
                    self._json(HTTPStatus.OK, {"ok": True, "cover_letter": generate_cover_letter(resume, job)}, origin)
                else:
                    questions = payload.get("questions", [])
                    if not isinstance(questions, list) or not all(isinstance(item, str) for item in questions):
                        raise ValueError("Questions must be a list of visible text prompts.")
                    result = match_resume_to_job(resume, job) if job.job_description else None
                    drafts = generate_draft_answers(questions[:20], job, result)
                    self._json(HTTPStatus.OK, {"ok": True, "drafts": [asdict(draft) for draft in drafts]}, origin)
                return
            self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Unknown endpoint."}, origin)
        except PermissionError as exc:
            self._json(HTTPStatus.FORBIDDEN, {"ok": False, "error": str(exc)}, origin)
        except (KeyError, FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)}, origin)
        except Exception as exc:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)}, origin)

    def do_DELETE(self) -> None:  # noqa: N802 - standard library handler hook
        origin = self.headers.get("Origin", "")
        identifier = self.path.removeprefix("/api/jobs/")
        if not _is_dashboard_origin(origin) or not self.path.startswith("/api/jobs/") or not identifier.isdigit():
            self._json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "Jobs can only be deleted from the local dashboard."})
            return
        try:
            self.store.delete(int(identifier))
            warning = self.store.export()
            response: dict[str, Any] = {"ok": True, "deleted_id": int(identifier)}
            if warning:
                response["excel_warning"] = warning
            self._json(HTTPStatus.OK, response)
        except KeyError as exc:
            self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": str(exc)})
        except Exception as exc:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})

    def _payload(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > MAX_REQUEST_BYTES:
            raise ValueError("The request has an invalid size.")
        if not length:
            return {}
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("The request body must be a JSON object.")
        return value

    def _json(self, status: HTTPStatus, payload: dict[str, Any], origin: str = "") -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if _is_extension_origin(origin):
            self._cors_headers(origin)
        self.end_headers()
        self.wfile.write(body)

    def _html(self, document: str) -> None:
        body = document.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _tailored_resume(self, encoded_name: str) -> None:
        name = unquote(encoded_name)
        if not name or Path(name).name != name or not name.casefold().endswith(".pdf"):
            self.send_error(HTTPStatus.BAD_REQUEST)
            return
        path = self.store.settings.tailored_resume_dir / name
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Disposition", f'inline; filename="{name}"')
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _cors_headers(self, origin: str) -> None:
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Vary", "Origin")

    def log_message(self, format: str, *args: object) -> None:
        timestamp = datetime.now().astimezone().strftime("%H:%M:%S")
        print(f"[{timestamp}] {self.address_string()} - {format % args}")


def _is_extension_origin(origin: str) -> bool:
    return origin == CHROME_EXTENSION_ORIGIN


def _is_dashboard_origin(origin: str) -> bool:
    return origin == f"http://{HOST}:{PORT}"


def render_dashboard(jobs: list[Job]) -> str:
    """Render the compact live tracker; detailed capture fields remain in SQLite."""
    rows = []
    for job in jobs:
        score = "Analysis pending" if job.match_score is None else f"{job.match_score}%"
        resume = (
            f'<a href="/tailored/{html.escape(job.tailored_resume_path, quote=True)}" target="_blank" rel="noreferrer">Open tailored PDF</a>'
            if job.tailored_resume_path else "—"
        )
        metadata = " · ".join(filter(None, (job.location, job.workplace_type, job.employment_type, job.application_method))) or "Details not shown"
        captured = _dashboard_date(job.first_seen_at or job.date_found)
        last_seen = f"Seen {job.seen_count} time{'s' if job.seen_count != 1 else ''}"
        applied_date = _dashboard_date(job.applied_at) if job.applied else "Not applied"
        not_applied_selected = "" if job.applied else " selected"
        applied_selected = " selected" if job.applied else ""
        no_follow_up_selected = "" if job.followed_up else " selected"
        followed_up_selected = " selected" if job.followed_up else ""
        if job.followed_up:
            follow_up_detail = f"Followed up {_dashboard_date(job.followed_up_at)}"
        elif job.follow_up_date:
            follow_up_detail = f"Scheduled {_dashboard_date(job.follow_up_date)}"
        else:
            follow_up_detail = "Not followed up"
        rows.append(
            f'<tr class="{"applied-row" if job.applied else ""}">'
            f'<td class="position"><a href="{html.escape(job.url, quote=True)}" target="_blank" rel="noreferrer">{html.escape(job.title)}</a>'
            f'<strong>{html.escape(job.company)}</strong><small>{html.escape(metadata)}</small></td>'
            f"<td>{html.escape(captured)}<small>{html.escape(last_seen)}</small></td>"
            f"<td><b>{html.escape(score)}</b><small>{html.escape(job.recommendation or 'review manually')}</small></td>"
            f'<td><select class="applied-select" data-id="{job.id}" data-previous="{1 if job.applied else 0}" aria-label="Application status for {html.escape(job.title, quote=True)}">'
            f'<option value="0"{not_applied_selected}>Not applied</option><option value="1"{applied_selected}>Applied</option></select>'
            f'<small class="applied-date" data-id="{job.id}">{html.escape(applied_date)}</small></td>'
            f'<td><select class="follow-up-select" data-id="{job.id}" data-previous="{1 if job.followed_up else 0}" aria-label="Follow-up status for {html.escape(job.title, quote=True)}">'
            f'<option value="0"{no_follow_up_selected}>No</option><option value="1"{followed_up_selected}>Yes</option></select>'
            f'<small class="follow-up-detail" data-id="{job.id}">{html.escape(follow_up_detail)}</small></td>'
            f"<td>{resume}</td><td><button data-id=\"{job.id}\" class=\"delete\">Delete</button></td>"
            "</tr>"
        )
    table = "".join(rows) or '<tr><td colspan="7" class="empty">No LinkedIn jobs captured yet.</td></tr>'
    applied_count = sum(1 for job in jobs if job.applied)
    followed_up_count = sum(1 for job in jobs if job.followed_up)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LinkedIn Job Application Assistant</title><style>
:root{{--blue:#0a66c2;--ink:#162033;--muted:#657386;font-family:Segoe UI,Arial,sans-serif;color:var(--ink);background:#f3f6f9}}*{{box-sizing:border-box}}body{{margin:0}}header{{padding:30px 5vw;background:linear-gradient(135deg,#004182,var(--blue));color:#fff}}h1{{margin:0 0 7px;font-size:30px}}header p{{margin:0;opacity:.9}}main{{padding:24px 5vw}}.toolbar{{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:16px}}button,select{{border:0;border-radius:8px;padding:9px 12px;font:700 13px Segoe UI,Arial,sans-serif;cursor:pointer}}button{{background:var(--blue);color:#fff}}button.delete{{background:#b42318}}select{{border:1px solid #b9c8d8;background:#fff;color:var(--ink)}}select:disabled{{opacity:.6;cursor:wait}}#status{{min-height:18px;color:#b42318;font-size:13px}}#status.ok{{color:#057642}}.card{{overflow:auto;border-radius:13px;background:#fff;box-shadow:0 5px 20px #1b365515}}table{{width:100%;border-collapse:collapse;min-width:900px}}th,td{{padding:14px 15px;border-bottom:1px solid #e7edf3;text-align:left;vertical-align:top}}th{{background:#f8fafc;font-size:12px;text-transform:uppercase;color:#526173}}tr.applied-row{{background:#f5fbf7}}a{{color:var(--blue);font-weight:750;text-decoration:none}}.position strong,.position small,td small{{display:block;margin-top:5px}}small{{color:var(--muted)}}.empty{{padding:38px;text-align:center;color:var(--muted)}}@media(max-width:700px){{header,main{{padding-left:20px;padding-right:20px}}h1{{font-size:24px}}}}</style></head>
<body><header><h1>LinkedIn Job Application Assistant</h1><p>{len(jobs)} job{'s' if len(jobs) != 1 else ''} captured · {applied_count} marked applied · {followed_up_count} followed up · Updates appear automatically</p></header>
<main><div class="toolbar"><button id="rematch">Match newest resume again</button><button id="clear">Clear all saved data</button><span id="status" role="status"></span></div>
<div class="card"><table><thead><tr><th>Position</th><th>Captured</th><th>Match</th><th>Applied?</th><th>Followed up?</th><th>Resume</th><th></th></tr></thead><tbody>{table}</tbody></table></div></main>
<script>
const status=document.querySelector('#status');
async function request(path,options={{}}){{const r=await fetch(path,options);const p=await r.json().catch(()=>({{}}));if(!r.ok||!p.ok)throw new Error(p.error||'The request did not finish.');return p}}
document.querySelectorAll('.applied-select').forEach(select=>select.onchange=async()=>{{const previous=select.dataset.previous;select.disabled=true;status.className='';status.textContent='Saving application status…';try{{const p=await request('/api/jobs/'+select.dataset.id+'/application',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{applied:select.value==='1'}})}});select.dataset.previous=p.job.applied?'1':'0';document.querySelector('.applied-date[data-id="'+select.dataset.id+'"]').textContent=p.job.applied?(p.job.applied_at||'Applied'):'Not applied';status.className='ok';status.textContent=p.job.applied?'Marked as applied.':'Marked as not applied.'}}catch(e){{select.value=previous;status.className='';status.textContent=e.message}}finally{{select.disabled=false}}}});
document.querySelectorAll('.follow-up-select').forEach(select=>select.onchange=async()=>{{const previous=select.dataset.previous;select.disabled=true;status.className='';status.textContent='Saving follow-up status…';try{{const p=await request('/api/jobs/'+select.dataset.id+'/follow-up',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{followed_up:select.value==='1'}})}});select.dataset.previous=p.job.followed_up?'1':'0';document.querySelector('.follow-up-detail[data-id="'+select.dataset.id+'"]').textContent=p.job.followed_up?'Followed up':'Not followed up';status.className='ok';status.textContent=p.job.followed_up?'Marked as followed up.':'Marked as not followed up.'}}catch(e){{select.value=previous;status.className='';status.textContent=e.message}}finally{{select.disabled=false}}}});
document.querySelector('#rematch').onclick=async()=>{{try{{status.textContent='Matching queued…';await request('/api/jobs/rematch',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:'{{}}'}});status.textContent='Matching is running in the background.'}}catch(e){{status.textContent=e.message}}}};
document.querySelector('#clear').onclick=async()=>{{if(prompt('Type DELETE to remove saved jobs, the Excel tracker, and tailored PDFs.')!=='DELETE')return;try{{await request('/api/jobs/clear',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{confirmation:'DELETE'}})}});location.reload()}}catch(e){{status.textContent=e.message}}}};
document.querySelectorAll('.delete').forEach(b=>b.onclick=async()=>{{if(!confirm('Delete this saved job?'))return;try{{await request('/api/jobs/'+b.dataset.id,{{method:'DELETE'}});location.reload()}}catch(e){{status.textContent=e.message}}}});
let revision='{_revision(jobs)}';setInterval(async()=>{{try{{const p=await request('/api/jobs');if(p.revision!==revision)location.reload()}}catch(_){{}}}},2500);
</script></body></html>"""


def _dashboard_date(value: str | None) -> str:
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.strftime("%d %b %Y")
    except ValueError:
        return value


def run() -> None:
    """Start the local-only companion before refresh work so its dashboard is ready immediately."""
    settings = get_settings()
    store = LinkedInStore(settings)
    processor = BackgroundProcessor(store)
    CompanionHandler.store = store
    CompanionHandler.processor = processor
    server = ThreadingHTTPServer((HOST, PORT), CompanionHandler)
    server_thread = threading.Thread(target=server.serve_forever, name="linkedin-dashboard", daemon=True)
    server_thread.start()
    print("LinkedIn Chrome companion is running locally.")
    print(f"Dashboard: http://{HOST}:{PORT}/")
    try:
        # The dashboard is already available while this one-time startup refresh
        # exports existing rows and queues resume matching.
        store.export()
        queued = processor.enqueue_all()
        print(f"Queued {queued} saved job(s) for resume refresh. Leave this window open while using the extension.")
        while server_thread.is_alive():
            server_thread.join(timeout=0.5)
    except KeyboardInterrupt:
        print("\nStopping LinkedIn Chrome companion.")
    finally:
        server.shutdown()
        server_thread.join(timeout=3)
        server.server_close()
        processor.close()


if __name__ == "__main__":
    run()
