import unittest
import tempfile
from pathlib import Path

from job_assistant.models import Job
from job_assistant.resume_matcher import extract_skills, match_resume_to_job
from job_assistant.draft_answers import generate_draft_answers
from job_assistant.cover_letter import generate_cover_letter
from job_assistant.scraper import _build_capture_notes, _company_before_title, _description_from_visible_text, _header_from_visible_text, _is_job_title
from job_assistant.tailored_resume import _contact_lines, _experience_blocks, _ordered_experience_blocks, create_tailored_resume


class ResumeMatcherTests(unittest.TestCase):
    def test_scores_known_skill_coverage(self) -> None:
        job = Job("Data Analyst", "Example", "https://example.test/job", job_description="Use Python, SQL, Excel, Tableau, and Power BI.")
        result = match_resume_to_job("Python SQL Excel Tableau", job)
        self.assertEqual(result.score, 80)
        self.assertEqual(result.missing_skills, ["power bi"])
        self.assertEqual(result.recommendation, "apply")

    def test_sparse_description_requires_manual_review(self) -> None:
        job = Job("Analyst", "Example", "https://example.test/job2", job_description="Great communication required.")
        self.assertEqual(match_resume_to_job("communication", job).recommendation, "review manually")

    def test_soft_skills_do_not_contribute_to_a_match_score(self) -> None:
        skills = extract_skills("leadership communication teamwork stakeholder management customer service")
        self.assertEqual(skills, [])

    def test_objective_technical_skills_remain_matchable(self) -> None:
        skills = extract_skills("Python, HTML, SQL, coding, ETL, and data warehousing")
        self.assertEqual(skills, ["python", "sql", "html", "coding", "etl"])

    def test_etl_synonyms_do_not_create_multiple_missing_skills(self) -> None:
        job = Job(
            "Data Engineer", "Example", "https://example.test/job-etl",
            job_description="Use Python to build data pipelines, data transformation, data analysis, data quality, and data engineering.",
        )
        result = match_resume_to_job("Python experience building ETL workflows.", job)
        self.assertEqual(result.score, 100)
        self.assertEqual(result.matching_skills, ["python", "etl"])
        self.assertEqual(result.missing_skills, [])

    def test_pdf_whitespace_does_not_hide_power_bi_docker_or_machine_learning(self) -> None:
        skills = extract_skills("Power   BI, Docker, and machine\nlearning")
        self.assertEqual(skills, ["power bi", "docker", "machine learning"])

    def test_sensitive_question_requires_manual_answer(self) -> None:
        job = Job("Analyst", "Example", "https://example.test/job3")
        draft = generate_draft_answers(["What is your gender?"], job, None)[0]
        self.assertIn("Manual answer required", draft.answer)

    def test_cover_letter_only_uses_matching_skills(self) -> None:
        job = Job("Data Analyst", "Example", "https://example.test/job4", job_description="Use Python and SQL.")
        letter = generate_cover_letter("Python experience", job)
        self.assertIn("Python", letter)
        self.assertNotIn("SQL experience", letter)
        self.assertNotIn("certification", letter.casefold())

    def test_linkedin_visible_header_fallback_finds_company(self) -> None:
        header = "Micron Technology\nData Scientist\nSingapore, Singapore"
        self.assertEqual(_company_before_title(header, "Data Scientist"), "Micron Technology")

    def test_linkedin_metadata_fallback_finds_visible_header(self) -> None:
        header = _header_from_visible_text(
            "GoTo Group\nGojek - Data Scientist\nSingapore, Singapore · Reposted 2 weeks ago · Over 100 people clicked apply"
        )
        self.assertEqual(header.company, "GoTo Group")
        self.assertEqual(header.title, "Gojek - Data Scientist")

    def test_easy_apply_label_is_not_treated_as_a_job_title(self) -> None:
        self.assertFalse(_is_job_title("Easy Apply"))
        self.assertTrue(_is_job_title("Data Engineer"))

    def test_capture_notes_include_visible_description_and_skills(self) -> None:
        notes = _build_capture_notes("Use Python, SQL, and Tableau.", ["python", "sql", "tableau"], "Follow up next week")
        self.assertIn("Skills mentioned: python, sql, tableau", notes)
        self.assertIn("Job description: Use Python, SQL, and Tableau.", notes)
        self.assertIn("Personal note: Follow up next week", notes)

    def test_about_the_job_visible_text_fallback_extracts_requirements(self) -> None:
        page_text = "Header\nAbout the job\nJob Description:\nUse ETL pipelines and data warehousing.\nMeet the hiring team\nOther content"
        description = _description_from_visible_text(page_text)
        self.assertEqual(description, "Job Description:\nUse ETL pipelines and data warehousing.")

    def test_tailored_resume_uses_only_matching_skills_and_source_text(self) -> None:
        job = Job("Data Analyst", "Example", "https://example.test/job5", id=5, job_description="Use Python and SQL.")
        result = match_resume_to_job("Python experience at Original Employer", job)
        with tempfile.TemporaryDirectory() as directory:
            output = create_tailored_resume("Python experience at Original Employer", job, result, Path(directory))
            self.assertEqual(output.suffix, ".pdf")
            self.assertTrue(output.is_file())
            from pypdf import PdfReader
            content = "\n".join(page.extract_text() or "" for page in PdfReader(output).pages)
            self.assertIn("Python", content)
            self.assertIn("Original Employer", content)
            self.assertNotIn("SQL\n", content)

    def test_tailored_resume_splits_each_experience_for_readable_layout(self) -> None:
        source = (
            "Example Company | Data Analyst Jan 2024 - Present "
            "1. Built Python pipelines. 2. Created SQL reports. "
            "Earlier Company | Analyst Jan 2022 - Dec 2023 "
            "1. Maintained dashboards."
        )
        blocks = _experience_blocks(source)
        self.assertEqual(len(blocks), 2)
        self.assertIn("Example Company", blocks[0][0])
        self.assertEqual(blocks[0][1], ["1. Built Python pipelines.", "2. Created SQL reports."])

    def test_related_analyst_and_engineer_roles_keep_source_chronology(self) -> None:
        blocks = [
            ("Recent NUH | Data Engineer Jan 2025 - Present", ["Built ETL workflows."]),
            ("Earlier MOH | Data Analyst Jan 2023 - Dec 2024", ["Built Python and SQL reports."]),
        ]
        ordered = _ordered_experience_blocks(blocks, "Data Engineer", ["python", "sql", "etl"])
        self.assertEqual(ordered, blocks)

    def test_only_clearly_unrelated_roles_move_after_related_experience(self) -> None:
        blocks = [
            ("Recent NUH | Data Engineer Jan 2025 - Present", ["Built ETL workflows."]),
            ("Retail Shop | Cashier Jan 2024 - Dec 2024", ["Handled payments."]),
            ("Earlier MOH | Data Analyst Jan 2023 - Dec 2023", ["Built SQL reports."]),
        ]
        ordered = _ordered_experience_blocks(blocks, "Data Engineer", ["python", "sql", "etl"])
        self.assertEqual([header for header, _ in ordered], [blocks[0][0], blocks[2][0], blocks[1][0]])

    def test_tailored_resume_preserves_name_and_contact_as_separate_header_lines(self) -> None:
        name, details = _contact_lines("Jane Doe 91234567 | jane@example.com | linkedin.com/in/jane")
        self.assertEqual(name, "Jane Doe")
        self.assertEqual(details, "91234567 | jane@example.com | linkedin.com/in/jane")
