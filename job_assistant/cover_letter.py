from __future__ import annotations

from .models import Job
from .resume_matcher import MatchResult, match_resume_to_job


def generate_cover_letter(resume_text: str, job: Job) -> str:
    """Create a concise, evidence-bound cover letter from local resume and job text."""
    result = match_resume_to_job(resume_text, job)
    matching = result.matching_skills
    skill_phrase = _skill_phrase(matching)
    role_skills = _skill_phrase(_job_skills(result))

    paragraphs = [
        "Dear Hiring Team,",
        f"I am writing to express my interest in the {job.title} role at {job.company}.",
    ]
    if matching:
        paragraphs.append(
            f"My resume reflects experience with {skill_phrase}, which aligns with the skills emphasized in the job description{': ' + role_skills if role_skills else ''}."
        )
    else:
        paragraphs.append(
            "I reviewed the job description and am interested in learning more about how my background may support the needs of this role."
        )
    paragraphs.append(
        f"I am drawn to the opportunity to contribute to {job.company} in this position. I would welcome the chance to discuss the relevant experience described in my resume and how it may apply to the role."
    )
    paragraphs.extend(["Thank you for your consideration.", "Sincerely,"])
    return "\n\n".join(paragraphs)


def _job_skills(result: MatchResult) -> list[str]:
    return result.matching_skills + result.missing_skills


def _skill_phrase(skills: list[str]) -> str:
    skills = [_display_skill(skill) for skill in skills]
    if not skills:
        return "the role's stated requirements"
    if len(skills) == 1:
        return skills[0]
    if len(skills) == 2:
        return f"{skills[0]} and {skills[1]}"
    return f"{', '.join(skills[:-1])}, and {skills[-1]}"


def _display_skill(skill: str) -> str:
    acronyms = {"sql", "aws", "gcp", "api", "etl", "seo", "sap", "jira", "github", "excel", "power bi"}
    return skill.upper() if skill in acronyms else skill.title()
