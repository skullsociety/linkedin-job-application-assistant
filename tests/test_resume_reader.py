import os
import tempfile
import unittest
from pathlib import Path

from job_assistant.resume_reader import latest_resume


class ResumeReaderTests(unittest.TestCase):
    def test_latest_resume_uses_most_recent_pdf_or_docx(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            older = folder / "older.pdf"
            newest = folder / "newest.docx"
            ignored = folder / "notes.txt"
            older.touch()
            newest.touch()
            ignored.touch()
            os.utime(older, (1, 1))
            os.utime(newest, (2, 2))
            self.assertEqual(latest_resume(folder), newest)

    def test_latest_resume_requires_a_supported_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(FileNotFoundError, "No PDF or DOCX"):
                latest_resume(Path(directory))
