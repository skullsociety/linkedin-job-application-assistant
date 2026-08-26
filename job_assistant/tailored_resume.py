"""ATS-readable tailored PDF resumes built only from local source-resume content."""

from __future__ import annotations

import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer

from .models import Job
from .resume_matcher import MatchResult


SECTION_ORDER = (
    "Professional Summary",
    "Professional Experience",
    "Projects",
    "Education",
    "Certifications and Professional Development",
    "Core Skills",
    "Additional Information",
)

_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
_DATE_RANGE = rf"{_MONTH}\s+\d{{4}}\s*(?:-|–)\s*(?:Present|{_MONTH}\s+\d{{4}})"
# A source entry usually has "Employer | Role", and the one no-pipe entry in
# the supplied resume is still recognisable by its role suffix.  Avoiding full
# stops in the employer/role part prevents a numbered accomplishment from
# accidentally being treated as the start of the next entry.
_EXPERIENCE_START = r"(?:[A-Z][^.|]{1,90}\|\s*[^.]{1,90}|[A-Z][A-Za-z &()/\-]{2,120}(?:Resident|Intern|Consultant|Specialist|Engineer|Analyst|Officer|Technician|Developer))"
_EXPERIENCE_HEADER = re.compile(rf"(?P<header>{_EXPERIENCE_START}\s+{_DATE_RANGE})(?=\s+\d+[.)]\s*)")

# Data, software, analytics, engineering, and technical roles belong to the
# same broad job family for ordering purposes.  A Data Analyst and a Data
# Engineer therefore remain in the source resume's reverse-chronological
# sequence, even when one block happens to mention more job keywords.
TECHNICAL_ROLE_MARKERS = frozenset({
    "analyst", "analytics", "architect", "automation", "bi", "data", "developer",
    "development", "engineer", "engineering", "information technology", "it", "machine learning",
    "scientist", "science", "software", "systems", "technology",
})
_COMMON_TITLE_WORDS = frozenset({"and", "assistant", "associate", "contract", "executive", "intern", "junior", "lead", "manager", "senior", "specialist", "staff", "the", "to"})


def create_tailored_resume(resume_text: str, job: Job, match: MatchResult, output_dir: Path) -> Path:
    """Create a truthful, readable PDF that prioritizes verified matching terms."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"tailored_resume_{_safe_name(job.company)}_{_safe_name(job.title)}_{job.id or 'job'}.pdf"
    document = SimpleDocTemplate(
        str(output),
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=18 * mm,
        bottomMargin=13 * mm,
        title=f"Tailored Resume - {job.title}",
        author="Linkedin Job Application Assistant",
    )
    styles = _styles()
    contact, sections = _split_resume(resume_text)
    name, details = _contact_lines(contact)
    story = [Paragraph(_escape(name or "Resume"), styles["name"])]
    if details:
        story.append(Paragraph(_escape(details), styles["contact"]))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("Relevant Skills", styles["heading"]))
    if match.matching_skills:
        skills = ", ".join(_display_skill(skill) for skill in match.matching_skills)
        story.append(Paragraph(_escape(skills), styles["body"]))
    else:
        story.append(Paragraph("No job skills were detected in both the source resume and this job description.", styles["body"]))
    story.append(Spacer(1, 1.5 * mm))

    for heading in SECTION_ORDER:
        content = sections.get(heading)
        if not content:
            continue
        story.append(Paragraph(heading, styles["heading"]))
        if heading == "Professional Experience":
            story.extend(_experience_flowables(content, styles, job.title, match.matching_skills))
        else:
            story.extend(_content_paragraphs(content, styles))
        story.append(Spacer(1, 2 * mm))
    if not sections:
        story.append(Paragraph("Original Resume Content", styles["heading"]))
        story.extend(_content_paragraphs(_normalize(resume_text), styles))
    document.build(story)
    return output


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        # These measurements intentionally mirror the original: a 14pt centred name
        # followed by 11pt centred contact details.
        "name": ParagraphStyle("Name", parent=base["Title"], fontName="Helvetica-Bold", fontSize=14, leading=17, alignment=TA_CENTER, textColor=colors.black, spaceAfter=0.5 * mm),
        "contact": ParagraphStyle("Contact", parent=base["Normal"], fontName="Helvetica", fontSize=11, leading=13, alignment=TA_CENTER, textColor=colors.black, spaceAfter=0),
        # Standard, searchable headings are deliberately larger than job titles
        # and body text.  This creates a clear human hierarchy without tables,
        # columns, icons, text boxes, or other ATS-unfriendly layout devices.
        "heading": ParagraphStyle("Heading", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=colors.HexColor("#17365D"), spaceBefore=3.5 * mm, spaceAfter=1.7 * mm, keepWithNext=True),
        "body": ParagraphStyle("Body", parent=base["Normal"], fontName="Helvetica", fontSize=9.5, leading=12.5, spaceAfter=1.5 * mm),
        "experience_header": ParagraphStyle("ExperienceHeader", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=10.3, leading=13.4, textColor=colors.HexColor("#17365D"), spaceBefore=1.8 * mm, spaceAfter=1 * mm),
        "bullet": ParagraphStyle("Bullet", parent=base["Normal"], fontName="Helvetica", fontSize=9.4, leading=12.4, leftIndent=4 * mm, firstLineIndent=-3 * mm, bulletIndent=0, spaceAfter=1.2 * mm),
    }


def _split_resume(resume_text: str) -> tuple[str, dict[str, str]]:
    text = _normalize(resume_text)
    heading_pattern = "|".join(re.escape(heading) for heading in sorted(SECTION_ORDER, key=len, reverse=True))
    matches = list(re.finditer(heading_pattern, text, re.IGNORECASE))
    if not matches:
        return text[:180], {}
    contact = text[:matches[0].start()].strip()
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        canonical_heading = next(heading for heading in SECTION_ORDER if heading.casefold() == match.group(0).casefold())
        sections[canonical_heading] = text[match.end():end].strip()
    return contact, sections


def _contact_lines(contact: str) -> tuple[str, str]:
    """Separate the name from contact details without inventing either."""
    phone = re.search(r"\b\d{8,}\b", contact)
    if phone:
        return contact[:phone.start()].strip(" |"), contact[phone.start():].strip()
    parts = re.split(r"\s*\|\s*", contact, maxsplit=1)
    return (parts[0], " | ".join(parts[1:])) if len(parts) > 1 else (contact, "")


def _experience_flowables(
    content: str,
    styles: dict[str, ParagraphStyle],
    job_title: str,
    matching_skills: list[str],
) -> list[object]:
    """Render distinct experience blocks, retaining chronology for related roles."""
    blocks = _experience_blocks(content)
    if not blocks:
        return _content_paragraphs(content, styles)

    # The source resume is newest-first.  Do not promote an older Data Analyst,
    # Engineer, or similar role simply because its bullets contain more exact
    # keywords.  Move an entry only when it is clearly outside the target job's
    # technical family and has no matching-skill evidence.
    ranked = _ordered_experience_blocks(blocks, job_title, matching_skills)
    flowables: list[object] = []
    for header, bullets in ranked:
        title = Paragraph(_escape(header), styles["experience_header"])
        items = [Paragraph(_escape(_clean_bullet(bullet)), styles["bullet"], bulletText="•") for bullet in bullets]
        if items:
            flowables.append(KeepTogether([title, items[0]]))
            flowables.extend(items[1:])
        else:
            flowables.append(title)
        flowables.append(Spacer(1, 2.2 * mm))
    return flowables


def _ordered_experience_blocks(
    blocks: list[tuple[str, list[str]]],
    job_title: str,
    matching_skills: list[str],
) -> list[tuple[str, list[str]]]:
    """Keep source chronology, moving only clearly unrelated entries to the end."""
    return [
        block
        for _, block in sorted(
            enumerate(blocks),
            key=lambda item: (
                0 if _is_related_experience(item[1], job_title, matching_skills) else 1,
                item[0],
            ),
        )
    ]


def _is_related_experience(block: tuple[str, list[str]], job_title: str, matching_skills: list[str]) -> bool:
    """Return true unless a role is clearly outside a technical target's job family."""
    header, bullets = block
    role = _role_from_header(header)
    target_words = _meaningful_words(job_title)
    role_words = _meaningful_words(role)
    if target_words & role_words:
        return True

    target_is_technical = _contains_technical_marker(job_title)
    role_is_technical = _contains_technical_marker(role)
    if target_is_technical and role_is_technical:
        return True

    evidence = " ".join((header, *bullets)).casefold()
    if any(re.search(rf"(?<!\w){re.escape(skill.casefold())}(?!\w)", evidence) for skill in matching_skills):
        return True

    # When a target itself is not clearly technical, order is more subjective;
    # preserve chronology rather than making a weak automatic judgement.
    return not target_is_technical


def _role_from_header(header: str) -> str:
    """Extract the role portion without the employer name or date range."""
    role = header.split("|", 1)[-1] if "|" in header else header
    return re.sub(rf"\s+{_DATE_RANGE}\s*$", "", role, flags=re.IGNORECASE).strip()


def _meaningful_words(value: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z]+", value.casefold())
        if len(word) > 2 and word not in _COMMON_TITLE_WORDS
    }


def _contains_technical_marker(value: str) -> bool:
    normalized = value.casefold()
    return any(re.search(rf"(?<!\w){re.escape(marker)}(?!\w)", normalized) for marker in TECHNICAL_ROLE_MARKERS)


def _experience_blocks(content: str) -> list[tuple[str, list[str]]]:
    """Split the flattened source text into employer/role/date and bullet groups."""
    matches = list(_EXPERIENCE_HEADER.finditer(content))
    blocks: list[tuple[str, list[str]]] = []
    for index, match in enumerate(matches):
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        bullets = [part.strip() for part in re.split(r"(?=\b\d+[.)]\s*)", content[body_start:body_end]) if part.strip()]
        if bullets:
            blocks.append((match.group("header").strip(), bullets))
    return blocks


def _clean_bullet(value: str) -> str:
    return re.sub(r"^\d+[.)]\s*(?:-\s*)?", "", value).strip()


def _content_paragraphs(content: str, styles: dict[str, ParagraphStyle]) -> list[Paragraph]:
    chunks = [chunk.strip() for chunk in re.split(r"(?=\b\d+[.)]\s*)|\n{2,}", content) if chunk.strip()]
    return [Paragraph(_escape(_clean_bullet(chunk)), styles["bullet"], bulletText="•") if re.match(r"^\d+[.)]", chunk) else Paragraph(_escape(chunk), styles["body"]) for chunk in chunks]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")
    return cleaned[:48] or "job"


def _display_skill(skill: str) -> str:
    return skill.upper() if skill in {"sql", "aws", "gcp", "api", "etl", "seo", "sap", "jira", "github", "excel", "power bi"} else skill.title()
