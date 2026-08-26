from __future__ import annotations

import re
from dataclasses import dataclass

from playwright.async_api import Page

from .models import Job
from .resume_matcher import MatchResult


SENSITIVE_QUESTION_MARKERS = ("gender", "race", "ethnicity", "disability", "veteran", "date of birth", "age", "religion", "sexual orientation", "nationality")


@dataclass(frozen=True)
class DraftAnswer:
    question: str
    answer: str


async def collect_custom_questions(page: Page) -> list[str]:
    """Collect visible text-area prompts for review; does not enter any answer."""
    questions: list[str] = []
    for index in range(await page.locator("textarea").count()):
        textarea = page.locator("textarea").nth(index)
        if not await textarea.is_visible():
            continue
        label = await textarea.get_attribute("aria-label") or await textarea.get_attribute("placeholder")
        if label:
            questions.append(_clean(label))
            continue
        parent_text = await textarea.locator("xpath=ancestor-or-self::*[self::div or self::fieldset][1]").inner_text()
        if parent_text:
            questions.append(_clean(parent_text)[:500])
    return list(dict.fromkeys(question for question in questions if question))


def generate_draft_answers(questions: list[str], job: Job, result: MatchResult | None) -> list[DraftAnswer]:
    drafts: list[DraftAnswer] = []
    skills = ", ".join(result.matching_skills[:5]) if result and result.matching_skills else "relevant experience"
    for question in questions:
        lowered = question.casefold()
        if any(marker in lowered for marker in SENSITIVE_QUESTION_MARKERS):
            answer = "Manual answer required: this personal question should be answered directly by you."
        elif "why" in lowered and any(word in lowered for word in ("interest", "company", "role", "apply")):
            answer = f"I am interested in the {job.title} role at {job.company} because it aligns with my experience in {skills}. I would welcome the opportunity to contribute those strengths to the team."
        elif any(word in lowered for word in ("experience", "qualified", "background", "skill")):
            answer = f"My background includes {skills}, which align with the requirements highlighted for this {job.title} role. I would be glad to discuss relevant examples from my experience."
        else:
            answer = "Draft unavailable. Please answer this question in your own words after reviewing the prompt."
        drafts.append(DraftAnswer(question, answer))
    return drafts


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
