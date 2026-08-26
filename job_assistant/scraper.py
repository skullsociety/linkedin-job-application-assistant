from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse
from typing import Iterable, Optional

from playwright.async_api import Locator, Page

from .models import Job
from .resume_matcher import extract_skills


class ManualActionRequired(RuntimeError):
    """The user must handle an access or verification page in the visible browser."""


VERIFICATION_MARKERS = (
    "verify you are human", "security verification", "complete the security check",
    "confirm your identity", "unusual activity", "captcha", "robot check",
)

LINKEDIN_TITLE_SELECTORS = (
    "[data-test-id='job-title']",
    ".job-details-jobs-unified-top-card__job-title",
    "[data-view-name*='job-details'] h1",
    "[data-view-name*='job-details'] h2",
    "h1",
)

LINKEDIN_COMPANY_SELECTORS = (
    "[data-test-id='company-name']",
    ".job-details-jobs-unified-top-card__company-name a",
    ".job-details-jobs-unified-top-card__company-name",
    "[data-view-name*='job-details'] a[href*='/company/']",
    "a[href*='/company/']",
)

NON_JOB_TITLE_LABELS = frozenset({"easy apply", "apply", "save", "job details", "additional questions", "application"})

async def extract_job(page: Page, match_score: Optional[int], notes: Optional[str]) -> Job:
    """Read job details rendered and visible to the signed-in user; never bypasses access checks."""
    await ensure_accessible(page)

    visible_text = await page.locator("body").inner_text()
    visible_header = _header_from_visible_text(visible_text)
    title = await _first_visible_job_title(page, LINKEDIN_TITLE_SELECTORS + (".topcard__title",))
    title = title or visible_header.title
    company = await _first_visible_text(page, LINKEDIN_COMPANY_SELECTORS + (
        ".topcard__org-name-link", ".topcard__flavor--black-link",
    ))
    company = company or await _company_from_heading_context(page, title)
    company = company or _company_before_title(visible_text, title)
    company = company or visible_header.company
    if not title or not company:
        raise ManualActionRequired(
            "The job title or company is not visible yet. Navigate to a fully loaded job-detail page and try again."
        )

    top_card = await _first_visible_text(page, (
        ".job-details-jobs-unified-top-card__primary-description-container", ".topcard__flavor-row",
    )) or ""
    description = _description_from_visible_text(visible_text) or await _first_visible_text(page, (
        ".jobs-description-content__text",
        ".jobs-description__content",
        ".jobs-box__html-content",
        "[data-test-id='job-details']",
        "#job-details",
    ))
    return Job(
        title=title, company=company, url=page.url,
        platform=_platform_from_url(page.url),
        location=await _first_visible_text(page, (".job-details-jobs-unified-top-card__bullet", ".topcard__flavor--bullet")),
        job_description=description,
        workplace_type=_find_phrase(top_card, ("On-site", "Hybrid", "Remote")),
        applicant_count=_find_applicant_count(top_card),
        posting_date=_find_posting_date(top_card),
        match_score=match_score,
        notes=_build_capture_notes(description, extract_skills(description or ""), notes),
    )


async def ensure_accessible(page: Page) -> None:
    """Stop the workflow when the rendered page asks the user to verify or regain access."""
    visible_text = await page.locator("body").inner_text()
    if any(marker in visible_text.lower() for marker in VERIFICATION_MARKERS):
        raise ManualActionRequired(
            "The page is asking for verification or appears to restrict access. "
            "Complete it manually in the visible browser; this assistant will not interact with it."
        )


async def _first_visible_text(page: Page, selectors: Iterable[str]) -> Optional[str]:
    for selector in selectors:
        locator = page.locator(selector)
        for index in range(await locator.count()):
            item: Locator = locator.nth(index)
            if await item.is_visible():
                text = _clean(await item.inner_text())
                if text:
                    return text
    return None


async def _first_visible_job_title(page: Page, selectors: Iterable[str]) -> Optional[str]:
    """Read a job-card title without mistaking an open Easy Apply dialog for the listing."""
    for selector in selectors:
        locator = page.locator(selector)
        for index in range(await locator.count()):
            item: Locator = locator.nth(index)
            if not await item.is_visible():
                continue
            text = _clean(await item.inner_text())
            if not _is_job_title(text):
                continue
            in_dialog = await item.evaluate("element => Boolean(element.closest('[role=dialog], .artdeco-modal'))")
            if not in_dialog:
                return text
    return None


def _is_job_title(value: str) -> bool:
    """Exclude generic application-dialog labels that cannot be a role title."""
    return bool(value and len(value) <= 180 and value.casefold() not in NON_JOB_TITLE_LABELS)


async def _company_from_heading_context(page: Page, title: str | None) -> Optional[str]:
    """Read the first visible company-link immediately following the selected job title."""
    if not title:
        return None
    headings = page.locator("h1, h2")
    for index in range(await headings.count()):
        heading = headings.nth(index)
        if not await heading.is_visible() or _clean(await heading.inner_text()) != title:
            continue
        company_link = heading.locator("xpath=following::a[contains(@href, '/company/')][1]")
        if await company_link.count() and await company_link.is_visible():
            return _clean(await company_link.inner_text()) or None
    return None


def _company_before_title(visible_text: str, title: str | None) -> Optional[str]:
    """Use LinkedIn's visible header order: company line followed by job-title line."""
    if not title:
        return None
    lines = [_clean(line) for line in visible_text.splitlines()]
    for index, line in enumerate(lines):
        if line != title:
            continue
        for previous in reversed(lines[:index]):
            if previous:
                return previous
    return None


@dataclass(frozen=True)
class VisibleJobHeader:
    """Title and company inferred from the rendered job header's line order."""

    title: str | None = None
    company: str | None = None


def _header_from_visible_text(visible_text: str) -> VisibleJobHeader:
    """Find the company/title pair directly before a visible location/posting metadata line."""
    lines = [_clean(line) for line in visible_text.splitlines() if _clean(line)]
    for index, line in enumerate(lines):
        if index < 2 or not _looks_like_job_metadata(line):
            continue
        return VisibleJobHeader(title=lines[index - 1], company=lines[index - 2])
    return VisibleJobHeader()


def _looks_like_job_metadata(line: str) -> bool:
    lowered = line.casefold()
    indicators = ("reposted", "applicants", "clicked apply", "promoted by", "ago")
    return any(indicator in lowered for indicator in indicators) and ("," in line or "·" in line or "•" in line)


def _build_capture_notes(description: str | None, skills: list[str], user_note: str | None) -> str:
    """Create an auditable Notes value from rendered job text and optional user context."""
    sections = [
        f"Skills mentioned: {', '.join(skills) if skills else 'None recognized from the visible description.'}",
        f"Job description: {description or 'Not visible during capture. Re-capture after scrolling to the description.'}",
    ]
    if user_note and user_note.strip():
        sections.append(f"Personal note: {user_note.strip()}")
    return "\n\n".join(sections)


def _description_from_visible_text(visible_text: str) -> str | None:
    """Extract the rendered LinkedIn description beneath the current 'About the job' heading."""
    lines = [_clean(line) for line in visible_text.splitlines() if _clean(line)]
    start = next((index for index, line in enumerate(lines) if line.casefold() == "about the job"), None)
    if start is None:
        return None
    stop_markers = (
        "meet the hiring team", "job poster", "about the company", "similar jobs", "people also viewed",
        "show more", "show less", "set alert", "recommended for you",
    )
    description_lines: list[str] = []
    for line in lines[start + 1:]:
        if line.casefold() in stop_markers:
            break
        description_lines.append(line)
    return "\n".join(description_lines).strip() or None


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _find_phrase(text: str, phrases: Iterable[str]) -> Optional[str]:
    return next((phrase for phrase in phrases if re.search(rf"\b{re.escape(phrase)}\b", text, re.IGNORECASE)), None)


def _find_applicant_count(text: str) -> Optional[str]:
    match = re.search(r"(?:over\s+)?[\d,]+\s+applicants?", text, re.IGNORECASE)
    return match.group(0) if match else None


def _find_posting_date(text: str) -> Optional[str]:
    match = re.search(r"(?:reposted\s+)?\d+\s+(?:minute|hour|day|week|month)s?\s+ago", text, re.IGNORECASE)
    return match.group(0) if match else None


def _platform_from_url(url: str) -> str:
    hostname = urlparse(url).hostname or "Unknown"
    names = {"linkedin.com": "LinkedIn", "indeed.com": "Indeed", "glassdoor.com": "Glassdoor"}
    for domain, name in names.items():
        if hostname == domain or hostname.endswith(f".{domain}"):
            return name
    return hostname.removeprefix("www.").title()
