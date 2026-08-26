"""Command-line entry point for the local, human-in-the-loop assistant."""

from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
from collections.abc import Callable
from pathlib import Path
from threading import Event

from .browser import PersistentBrowser
from .config import Settings, get_settings
from .cover_letter import generate_cover_letter
from .database import VALID_STATUSES, JobRepository
from .draft_answers import DraftAnswer, collect_custom_questions, generate_draft_answers
from .exporter import export_jobs
from .form_filler import fill_common_fields
from .logging_config import configure_logging
from .models import Job
from playwright.async_api import Page
from .profile import load_profile
from .resume_matcher import MatchResult, match_resume_to_job
from .resume_reader import latest_resume, read_resume
from .scraper import ManualActionRequired, ensure_accessible, extract_job
from .tailored_resume import create_tailored_resume

LOG = logging.getLogger(__name__)


def parser() -> argparse.ArgumentParser:
    """Create the CLI parser without performing any local writes."""
    app = argparse.ArgumentParser(description="Linkedin Job Application Assistant")
    app.add_argument("--config", type=Path, help="Optional local TOML configuration file")
    commands = app.add_subparsers(dest="command", required=True)

    capture = commands.add_parser("capture", help="Save the job in the active browser tab")
    capture.add_argument("--score", type=int)
    capture.add_argument("--notes")
    commands.add_parser("login", help="Open the persistent browser for a manual first-time login")

    listing = commands.add_parser("list", help="List tracked jobs")
    listing.add_argument("--status", choices=sorted(VALID_STATUSES))
    update = commands.add_parser("update", help="Update tracker fields")
    update.add_argument("id", type=int)
    update.add_argument("--score", type=int)
    update.add_argument("--notes")
    update.add_argument("--status", choices=sorted(VALID_STATUSES))
    update.add_argument("--follow-up-date", help="YYYY-MM-DD")

    prepare = commands.add_parser("prepare", help="Open a job for manual review; never submits")
    prepare.add_argument("id", type=int)
    approve = commands.add_parser("approve-submit", help="Record approval; you still submit manually")
    approve.add_argument("id", type=int)
    approve.add_argument("--confirm", action="store_true", help="Required to record approval")
    export = commands.add_parser("export", help="Export all saved jobs to Excel")
    export.add_argument("--output", type=Path)
    commands.add_parser("clear-data", help="Delete saved jobs and generated tracker/resume outputs after confirmation")

    match = commands.add_parser("match-resume", help="Match a local PDF/DOCX resume against saved job descriptions")
    match.add_argument("resume", type=Path)
    match.add_argument("--job", type=int, help="Match one job ID; default matches all jobs with descriptions")
    latest_match = commands.add_parser("match-latest-resume", help="Match the newest PDF/DOCX from the configured resumes folder")
    latest_match.add_argument("--job", type=int, help="Match one job ID; default matches all jobs with descriptions")
    apply = commands.add_parser("apply", help="Interactive, non-submitting application assistant")
    apply.add_argument("id", type=int)
    letter = commands.add_parser("cover-letter", help="Create a short, evidence-bound cover-letter draft")
    letter.add_argument("id", type=int)
    letter.add_argument("resume", type=Path)
    letter.add_argument("--output", type=Path, help="Optional text-file destination")
    return app


async def login(settings: Settings) -> None:
    """Open the dedicated browser profile and wait for a manual sign-in."""
    async with PersistentBrowser(settings.browser_user_data_dir, settings.browser_channel) as browser:
        page = await browser.new_page()
        await page.goto("https://www.linkedin.com/", wait_until="domcontentloaded")
        await page.bring_to_front()
        input("Log in manually in the browser. No password is read or stored. Press Enter here when finished: ")


async def capture(
    repo: JobRepository,
    settings: Settings,
    score: int | None,
    notes: str | None,
    *,
    stop_event: Event | None = None,
    reporter: Callable[[str], None] = print,
) -> None:
    """Monitor one visible LinkedIn session and save each fully rendered job once."""
    async with PersistentBrowser(settings.browser_user_data_dir, settings.browser_channel) as browser:
        page = await browser.new_page()
        await page.goto("https://www.linkedin.com/jobs/", wait_until="domcontentloaded")
        await page.bring_to_front()
        reporter(
            "Automatic capture is running. Navigate to a job and scroll until About the job is visible; "
            "it will save and refresh the Excel tracker automatically. Press Ctrl+C when you are finished."
        )
        resume_text = _load_auto_match_resume(settings, reporter=reporter)
        captured_urls: set[str] = set()
        verification_notice_shown = False
        while not _stop_requested(stop_event):
            while not _stop_requested(stop_event):
                try:
                    job = await extract_job(await browser.active_page(), score, notes)
                    break
                except ManualActionRequired as exc:
                    if "verification" in str(exc).casefold() and not verification_notice_shown:
                        reporter(f"{exc} Monitoring resumes after you handle it manually.")
                        verification_notice_shown = True
                    await asyncio.sleep(1)
            if _stop_requested(stop_event):
                break
            verification_notice_shown = False
            if job.job_description and job.url not in captured_urls:
                saved = repo.upsert(job)
                captured_urls.add(job.url)
                reporter(f"Saved #{saved.id}: {saved.title} at {saved.company}")
                _auto_match_and_tailor(repo, saved, resume_text, settings, reporter=reporter)
                _refresh_tracker(repo, settings, reporter=reporter)
            await asyncio.sleep(1)
        reporter("Automatic capture stopped.")


async def prepare(repo: JobRepository, settings: Settings, job_id: int) -> None:
    """Open a saved job and hold the browser for manual review only."""
    job = _get_job(repo, job_id)
    async with PersistentBrowser(settings.browser_user_data_dir, settings.browser_channel) as browser:
        page = await browser.new_page()
        await page.goto(job.url, wait_until="domcontentloaded")
        await page.bring_to_front()
        input("Review and complete the application manually. This app will not submit it. Press Enter here when done: ")
    repo.update(job_id, score=None, notes=None, status="reviewing")
    print("Manual review ended. The assistant did not fill or submit any form.")


def match_resume(
    repo: JobRepository,
    resume_path: Path,
    job_id: int | None,
    settings: Settings,
    *,
    reporter: Callable[[str], None] = print,
) -> None:
    """Score one or all saved job descriptions against a local resume."""
    resume_text = read_resume(resume_path)
    jobs = [_get_job(repo, job_id)] if job_id else repo.list()
    matched_count = 0
    for job in jobs:
        if not job.job_description:
            reporter(f"#{job.id}: skipped - no saved job description")
            continue
        result = match_resume_to_job(resume_text, job)
        repo.save_match(
            _job_id(job),
            score=result.score,
            matching_skills=", ".join(result.matching_skills),
            missing_skills=", ".join(result.missing_skills),
            reason=result.reason,
            recommendation=result.recommendation,
        )
        reporter(f"#{job.id}: {result.score}/100 | {result.recommendation} | {result.reason}")
        if result.score >= settings.tailored_resume_threshold:
            output = create_tailored_resume(resume_text, job, result, settings.tailored_resume_dir)
            repo.set_tailored_resume_path(_job_id(job), output.name)
            reporter(f"  Tailored resume created: {output}")
        else:
            repo.set_tailored_resume_path(_job_id(job), None)
        matched_count += 1
    _refresh_tracker(repo, settings, reporter=reporter)
    reporter(f"Matched {matched_count} job(s). Tailored resumes are created at {settings.tailored_resume_threshold}% or above.")


def match_latest_resume(
    repo: JobRepository,
    job_id: int | None,
    settings: Settings,
    *,
    reporter: Callable[[str], None] = print,
) -> None:
    """Match using the most recently modified resume in the configured folder."""
    resume_path = latest_resume(settings.resume_dir)
    reporter(f"Using newest resume: {resume_path.name}")
    match_resume(repo, resume_path, job_id, settings, reporter=reporter)


async def application_flow(repo: JobRepository, job_id: int, settings: Settings) -> None:
    """Guide a user through reviewing and preparing an application without submitting it."""
    job = _get_job(repo, job_id)
    print_job_summary(job)
    if input("Continue to the listing? [y/N]: ").strip().casefold() not in {"y", "yes"}:
        print("Application flow cancelled.")
        return
    profile = load_profile(settings.profile_path)
    async with PersistentBrowser(settings.browser_user_data_dir, settings.browser_channel) as browser:
        page = await browser.new_page()
        await page.goto(job.url, wait_until="domcontentloaded")
        await page.bring_to_front()
        input("Open the application form yourself and complete any verification manually, then press Enter here: ")
        application_page = await _wait_for_accessible_page(browser)
        filled = await fill_common_fields(application_page, profile)
        description = ", ".join(filled) if filled else "none (fields may already be filled or use unsupported labels)"
        print(f"Filled common fields: {description}.")
        drafts = generate_draft_answers(
            await collect_custom_questions(application_page), job, _saved_match_result(job)
        )
        _print_drafts(drafts)
        confirmation = input("Review all fields and drafts. Type READY when you are ready to submit manually: ").strip()
        if confirmation == "READY":
            repo.record_submission_approval(job_id)
            print("Manual-submission approval recorded. Click the website's final submit button yourself when ready.")
        else:
            print("No submission approval recorded. The assistant did not submit anything.")


async def _wait_for_accessible_page(browser: PersistentBrowser) -> Page:
    """Return the current page only after the user resolves any visible access check."""
    while True:
        page = await browser.active_page()
        try:
            await ensure_accessible(page)
            return page
        except ManualActionRequired as exc:
            input(f"{exc}\nAfter resolving it manually, press Enter to continue: ")


def _saved_match_result(job: Job) -> MatchResult:
    """Convert stored match columns into the small structure used for answer drafts."""
    return MatchResult(
        score=job.match_score or 0,
        matching_skills=[skill for skill in (job.matching_skills or "").split(", ") if skill],
        missing_skills=[skill for skill in (job.missing_skills or "").split(", ") if skill],
        reason=job.match_reason or "No saved match result.",
        recommendation=job.recommendation or "review manually",
    )


def _load_auto_match_resume(settings: Settings, *, reporter: Callable[[str], None] = print) -> str | None:
    """Read the configured resume once so capture can match every newly saved job locally."""
    try:
        resume_path = latest_resume(settings.resume_dir)
        reporter(f"Using newest resume: {resume_path.name}")
        return read_resume(resume_path)
    except (OSError, ValueError) as exc:
        if settings.resume_path:
            try:
                reporter(f"Resume folder unavailable; using configured fallback: {settings.resume_path.name}")
                return read_resume(settings.resume_path)
            except (OSError, ValueError) as fallback_exc:
                reporter(f"Automatic resume matching is off: {fallback_exc}")
                return None
        reporter(f"Automatic resume matching is off: {exc}")
        return None


def _auto_match_and_tailor(
    repo: JobRepository,
    job: Job,
    resume_text: str | None,
    settings: Settings,
    *,
    reporter: Callable[[str], None] = print,
) -> None:
    """Persist a terminal-visible match result and write a tailored resume over the configured threshold."""
    if not resume_text:
        return
    result = match_resume_to_job(resume_text, job)
    saved = repo.save_match(
        _job_id(job),
        score=result.score,
        matching_skills=", ".join(result.matching_skills),
        missing_skills=", ".join(result.missing_skills),
        reason=result.reason,
        recommendation=result.recommendation,
    )
    reporter(f"Resume match: {result.score}/100 - {result.recommendation}. {result.reason}")
    if result.score >= settings.tailored_resume_threshold:
        output = create_tailored_resume(resume_text, saved, result, settings.tailored_resume_dir)
        repo.set_tailored_resume_path(_job_id(saved), output.name)
        reporter(f"Tailored resume created: {output}")
    else:
        repo.set_tailored_resume_path(_job_id(saved), None)


def _refresh_tracker(
    repo: JobRepository,
    settings: Settings,
    *,
    reporter: Callable[[str], None] = print,
) -> None:
    """Overwrite the configured tracker without stopping a workflow on an Excel file lock."""
    try:
        output = export_jobs(repo.list(), settings.export_path)
    except OSError as exc:
        LOG.warning("Automatic Excel export failed: %s", exc)
        reporter(f"Excel tracker was not refreshed. Close {settings.export_path.name} in Excel, then run another capture or resume match. ({exc})")
        return
    reporter(f"Excel tracker refreshed: {output}")


def _stop_requested(stop_event: Event | None) -> bool:
    """Return whether a GUI capture session has asked the async loop to finish."""
    return stop_event is not None and stop_event.is_set()


def _print_drafts(drafts: list[DraftAnswer]) -> None:
    if not drafts:
        print("No visible custom text questions found. Review the form manually.")
        return
    print("\nDraft answers for your review (not entered automatically):")
    for number, draft in enumerate(drafts, 1):
        print(f"{number}. Question: {draft.question}\n   Draft: {draft.answer}\n")


def print_job_summary(job: Job) -> None:
    """Display the saved job and match context before application preparation."""
    score = f"{job.match_score}/100" if job.match_score is not None else "Not matched"
    print(
        f"\n{job.title} - {job.company}\nLocation: {job.location or 'Not shown'}\n"
        f"Score: {score}\nRecommendation: {job.recommendation or 'review manually'}\n"
        f"Matching skills: {job.matching_skills or 'None saved'}\n"
        f"Missing skills: {job.missing_skills or 'None saved'}\n"
        f"Reason: {job.match_reason or 'No saved matching result'}\n"
    )


def cover_letter(repo: JobRepository, job_id: int, resume_path: Path, output: Path | None) -> None:
    """Create an evidence-bound cover-letter draft in the terminal or an explicit file."""
    job = _get_job(repo, job_id)
    if not job.job_description:
        raise ValueError("This job has no saved description. Capture the job page before generating a tailored letter.")
    letter = generate_cover_letter(read_resume(resume_path), job)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(letter, encoding="utf-8")
        print(f"Cover-letter draft written to {output}")
    else:
        print(letter)


def clear_saved_data(repo: JobRepository, settings: Settings) -> None:
    """Confirm and clear job records plus generated tracker and tailored-resume files."""
    confirmation = input(
        "Delete all saved job records and generated exports? Your browser login, profile, and source resume stay untouched. [Y/N]: "
    ).strip().casefold()
    if confirmation not in {"y", "yes"}:
        print("No saved data was deleted.")
        return
    removed_jobs = repo.delete_all()
    removed_outputs = _delete_generated_outputs(settings)
    print(f"Deleted {removed_jobs} saved job(s) and {removed_outputs} generated file(s).")


def _delete_generated_outputs(settings: Settings) -> int:
    """Remove only files produced by this assistant; preserve profile, browser, and configuration data."""
    removed = 0
    if settings.export_path.is_file():
        settings.export_path.unlink()
        removed += 1
    if settings.tailored_resume_dir.is_dir():
        removed += sum(1 for path in settings.tailored_resume_dir.rglob("*") if path.is_file())
        shutil.rmtree(settings.tailored_resume_dir)
    return removed


def _get_job(repo: JobRepository, job_id: int) -> Job:
    job = repo.get(job_id)
    if not job:
        raise KeyError(f"No job found with id {job_id}.")
    return job


def _job_id(job: Job) -> int:
    if job.id is None:
        raise RuntimeError("The saved job is missing a database identifier.")
    return job.id


def main() -> None:
    """Parse one command, configure logging, and return a concise user-facing error if needed."""
    args = parser().parse_args()
    settings = get_settings(args.config)
    configure_logging(settings.log_path)
    try:
        with JobRepository(settings.database_path) as repo:
            _run_command(args, settings, repo)
    except KeyboardInterrupt:
        print("\nAutomatic capture stopped. Returning to the launcher.")
    except (ValueError, KeyError, RuntimeError, OSError) as exc:
        LOG.error("%s", exc)
        raise SystemExit(f"Error: {exc}") from exc


def _run_command(args: argparse.Namespace, settings: Settings, repo: JobRepository) -> None:
    """Dispatch a parsed CLI command."""
    if args.command == "login":
        asyncio.run(login(settings))
    elif args.command == "match-resume":
        match_resume(repo, args.resume, args.job, settings)
    elif args.command == "match-latest-resume":
        match_latest_resume(repo, args.job, settings)
    elif args.command == "apply":
        asyncio.run(application_flow(repo, args.id, settings))
    elif args.command == "cover-letter":
        cover_letter(repo, args.id, args.resume, args.output)
    elif args.command == "capture":
        asyncio.run(capture(repo, settings, args.score, args.notes))
    elif args.command == "list":
        for job in repo.list(args.status):
            print(f"#{job.id} [{job.status}] {job.title} - {job.company} | {job.location or 'Location unavailable'}")
    elif args.command == "update":
        job = repo.update(args.id, score=args.score, notes=args.notes, status=args.status, follow_up_date=args.follow_up_date)
        print(f"Updated #{job.id}.")
    elif args.command == "prepare":
        asyncio.run(prepare(repo, settings, args.id))
    elif args.command == "approve-submit":
        if not args.confirm:
            raise ValueError("Approval was not recorded. Re-run with --confirm after reviewing the application.")
        job = repo.record_submission_approval(args.id)
        print(f"Approval recorded for #{job.id}. Submit manually in the browser when you are ready.")
    elif args.command == "export":
        jobs = repo.list()
        print(f"Exported {len(jobs)} jobs to {export_jobs(jobs, args.output or settings.export_path)}")
    elif args.command == "clear-data":
        clear_saved_data(repo, settings)
    else:
        raise RuntimeError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()
