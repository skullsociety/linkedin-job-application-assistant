from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Job


# Objective tools, technologies, technical methods, and measurable domain
# capabilities only.  Soft skills such as leadership, communication, teamwork,
# stakeholder management, and customer service must not change a match score.
#
# The ETL family deliberately consolidates broad job-description wording such
# as "data pipelines", "data quality", and "data engineering".  They are not
# independent missing skills when the resume already demonstrates ETL work.
SKILL_ALIASES: dict[str, tuple[str, ...]] = {
    "python": ("python",),
    "sql": ("sql",),
    "html": ("html",),
    "css": ("css",),
    "coding": ("coding",),
    "excel": ("excel",),
    "power bi": ("power bi", "powerbi"),
    "tableau": ("tableau",),
    "aws": ("aws",),
    "azure": ("azure",),
    "gcp": ("gcp",),
    "docker": ("docker",),
    "kubernetes": ("kubernetes",),
    "git": ("git",),
    "github": ("github",),
    "linux": ("linux",),
    "powershell": ("powershell",),
    "bash": ("bash",),
    "javascript": ("javascript",),
    "typescript": ("typescript",),
    "react": ("react",),
    "node.js": ("node.js",),
    "java": ("java",),
    "c#": ("c#",),
    "c++": ("c++",),
    "pandas": ("pandas",),
    "numpy": ("numpy",),
    "machine learning": (
        "machine learning", "deep learning", "scikit-learn", "tensorflow", "keras", "xgboost",
        "random forest", "adaboost", "natural language processing", "nlp", "computer vision",
        "time-series forecasting",
    ),
    "statistics": ("statistics",),
    "etl": (
        "etl", "elt", "data pipeline", "data pipelines", "pipeline automation", "data extraction",
        "data ingestion", "data transformation", "data validation", "data quality", "data analysis",
        "data analytics", "data engineering", "data modeling", "data warehousing",
    ),
    "api": ("api", "rest api"),
    "web scraping": ("web scraping", "web scraper"),
    "selenium": ("selenium",),
    "beautifulsoup": ("beautifulsoup",),
    "jira": ("jira",),
    "salesforce": ("salesforce",),
    "sap": ("sap",),
    "figma": ("figma",),
    "seo": ("seo",),
    "google analytics": ("google analytics",),
    "financial modeling": ("financial modeling",),
    "accounting": ("accounting",),
    "budgeting": ("budgeting",),
}

SKILL_VOCABULARY = tuple(SKILL_ALIASES)


@dataclass(frozen=True)
class MatchResult:
    score: int
    matching_skills: list[str]
    missing_skills: list[str]
    reason: str
    recommendation: str


def match_resume_to_job(resume_text: str, job: Job) -> MatchResult:
    """Compare recognized skills in local resume text with a saved job description."""
    job_text = " ".join(filter(None, (job.title, job.job_description, job.location, job.workplace_type)))
    job_skills = extract_skills(job_text)
    resume_skills = extract_skills(resume_text)
    matching = [skill for skill in job_skills if skill in resume_skills]
    missing = [skill for skill in job_skills if skill not in resume_skills]

    if not job.job_description or len(job_skills) < 2:
        return MatchResult(
            score=50, matching_skills=matching, missing_skills=missing,
            reason="The job description contains too few recognizable skills for a reliable automatic comparison.",
            recommendation="review manually",
        )

    coverage = len(matching) / len(job_skills)
    score = round(coverage * 100)
    if score >= 75:
        recommendation = "apply"
    elif score < 35:
        recommendation = "skip"
    else:
        recommendation = "review manually"
    reason = (
        f"Your resume matches {len(matching)} of {len(job_skills)} recognized skills "
        f"({round(coverage * 100)}% coverage) mentioned in this job description."
    )
    return MatchResult(score, matching, missing, reason, recommendation)


def extract_skills(text: str) -> list[str]:
    """Return canonical technical skills found in text, with equivalent terms merged."""
    normalized = re.sub(r"\s+", " ", text.casefold()).strip()
    return [
        skill
        for skill, aliases in SKILL_ALIASES.items()
        if any(re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", normalized) for alias in aliases)
    ]
