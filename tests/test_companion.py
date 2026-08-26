import tempfile
import unittest
from pathlib import Path

from companion.server import (
    CHROME_EXTENSION_ORIGIN,
    LinkedInStore,
    _is_extension_origin,
    payload_to_job,
    render_dashboard,
    serialize_job,
)
from job_assistant.config import Settings


class LinkedInCompanionTests(unittest.TestCase):
    def _settings(self, root: Path) -> Settings:
        return Settings(
            database_path=root / "data" / "jobs.sqlite3",
            export_path=root / "exports" / "job_tracker.xlsx",
            log_path=root / "logs" / "assistant.log",
            browser_user_data_dir=root / "data" / "browser-profile",
            browser_channel="chrome",
            profile_path=root / "data" / "profile.json",
            tailored_resume_dir=root / "exports" / "tailored_resumes",
            tailored_resume_threshold=70,
            resume_dir=root / "resumes",
            resume_path=None,
        )

    def _payload(self, url: str, description: str = "Use Python, SQL, and ETL data pipelines.") -> dict[str, str]:
        return {
            "title": "Data Engineer",
            "company": "Example Co",
            "url": url,
            "linkedin_job_id": "12345",
            "company_url": "https://www.linkedin.com/company/example-co/",
            "application_url": "https://jobs.example.test/apply/12345",
            "application_method": "External website",
            "location": "Singapore",
            "workplace_type": "Hybrid",
            "employment_type": "Full-time",
            "seniority_level": "Mid-Senior level",
            "posting_date": "2 days ago",
            "job_description": description,
        }

    def test_payload_uses_stable_linkedin_url_and_auditable_notes(self) -> None:
        job = payload_to_job(self._payload("https://www.linkedin.com/jobs/search-results/?currentJobId=12345&eBP=tracking"))
        self.assertEqual(job.url, "https://www.linkedin.com/jobs/view/12345/")
        self.assertEqual(job.platform, "LinkedIn")
        self.assertEqual(job.source, "linkedin")
        self.assertEqual(serialize_job(job)["source"], "linkedin")
        self.assertEqual(job.linkedin_job_id, "12345")
        self.assertEqual(job.application_method, "External website")
        self.assertEqual(job.employment_type, "Full-time")
        self.assertEqual(job.seniority_level, "Mid-Senior level")
        self.assertEqual(len(job.description_hash or ""), 64)
        self.assertIsNotNone(job.first_seen_at)
        self.assertIn("Skills mentioned: python, sql, etl", job.notes or "")
        self.assertIn("Job description: Use Python, SQL, and ETL data pipelines.", job.notes or "")

    def test_payload_requires_a_visible_description(self) -> None:
        with self.assertRaisesRegex(ValueError, "About the job"):
            payload_to_job(self._payload("https://www.linkedin.com/jobs/view/12345/", ""))

    def test_linkedin_and_extension_origin_checks_reject_lookalikes(self) -> None:
        with self.assertRaisesRegex(ValueError, "LinkedIn job listing"):
            payload_to_job(self._payload("https://evil-linkedin.com/jobs/view/12345/"))
        self.assertTrue(_is_extension_origin(CHROME_EXTENSION_ORIGIN))
        self.assertFalse(_is_extension_origin("chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"))

    def test_repeated_capture_updates_one_record_and_resets_old_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = LinkedInStore(self._settings(Path(directory)))
            first = store.upsert_capture(self._payload("https://www.linkedin.com/jobs/view/12345/"))
            store.save_analysis(first.id or 0, score=100, matching="python, sql, etl", missing="", reason="Old score", recommendation="apply")
            second = store.upsert_capture(self._payload("https://www.linkedin.com/jobs/search-results/?currentJobId=12345&eBP=other", "Use Python and Docker."))
            self.assertEqual(first.id, second.id)
            self.assertIsNone(second.match_score)
            self.assertEqual(second.recommendation, "analysis pending")
            self.assertIn("Docker", second.job_description or "")
            self.assertEqual(second.seen_count, 2)
            self.assertEqual(len(store.list()), 1)

    def test_dashboard_is_compact_and_has_applied_control(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = LinkedInStore(self._settings(Path(directory)))
            job = store.upsert_capture(self._payload("https://www.linkedin.com/jobs/view/12345/"))
            document = render_dashboard(store.list())
            self.assertIn("Applied?", document)
            self.assertIn('class="applied-select"', document)
            self.assertIn("Position", document)
            self.assertNotIn("<th>Source</th>", document)
            self.assertNotIn("<th>Matching skills</th>", document)
            store.set_applied(job.id or 0, True)
            updated = store.get(job.id or 0)
            self.assertTrue(updated.applied)
            self.assertIsNotNone(updated.applied_at)
