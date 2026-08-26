import unittest

from job_assistant.urls import canonicalize_job_url


class UrlTests(unittest.TestCase):
    def test_linkedin_current_job_id_becomes_stable_url(self) -> None:
        url = "https://www.linkedin.com/jobs/search-results/?currentJobId=12345&eBP=tracking"
        self.assertEqual(canonicalize_job_url(url), "https://www.linkedin.com/jobs/view/12345/")

    def test_generic_tracking_parameters_are_removed(self) -> None:
        url = "https://example.test/job/1?utm_source=newsletter&keep=yes#details"
        self.assertEqual(canonicalize_job_url(url), "https://example.test/job/1?keep=yes")

    def test_linkedin_lookalike_domain_is_not_treated_as_linkedin(self) -> None:
        url = "https://evil-linkedin.com/jobs/view/4378574897/?utm_source=test"
        self.assertEqual(canonicalize_job_url(url), "https://evil-linkedin.com/jobs/view/4378574897")
