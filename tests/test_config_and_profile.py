import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from job_assistant.config import ROOT, get_settings
from job_assistant.profile import load_profile


class ConfigAndProfileTests(unittest.TestCase):
    def test_toml_paths_resolve_from_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "settings.toml"
            config.write_text('database_path = "private/jobs.sqlite3"\nbrowser = "chromium"\n', encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                settings = get_settings(config)
            self.assertEqual(settings.database_path, ROOT / "private" / "jobs.sqlite3")
            self.assertIsNone(settings.browser_channel)

    def test_environment_overrides_toml(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "settings.toml"
            config.write_text('browser = "chromium"\n', encoding="utf-8")
            with patch.dict(os.environ, {"JOB_ASSISTANT_BROWSER": "chrome"}, clear=True):
                settings = get_settings(config)
            self.assertEqual(settings.browser_channel, "chrome")

    def test_default_tailored_resume_threshold_is_70(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = get_settings(ROOT / "missing-config.toml")
        self.assertEqual(settings.tailored_resume_threshold, 70)

    def test_config_accepts_optional_resume_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "settings.toml"
            resume_path = (Path(directory) / "resumes" / "target.pdf").resolve()
            config.write_text(f'resume_path = "{resume_path.as_posix()}"\n', encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                settings = get_settings(config)
            self.assertEqual(settings.resume_path, resume_path)

    def test_config_uses_a_resume_folder_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = get_settings(ROOT / "missing-config.toml")
        self.assertEqual(settings.resume_dir, ROOT / "resumes")

    def test_config_accepts_a_custom_resume_folder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "settings.toml"
            config.write_text('resume_dir = "private/resumes"\n', encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                settings = get_settings(config)
            self.assertEqual(settings.resume_dir, ROOT / "private" / "resumes")

    def test_runtime_home_relocates_all_default_user_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime_root = Path(directory).resolve()
            with patch.dict(os.environ, {"JOB_ASSISTANT_HOME": str(runtime_root)}, clear=True):
                settings = get_settings()
            self.assertEqual(settings.database_path, runtime_root / "data" / "jobs.sqlite3")
            self.assertEqual(settings.export_path, runtime_root / "exports" / "job_tracker.xlsx")
            self.assertEqual(settings.resume_dir, runtime_root / "resumes")

    def test_relative_environment_config_resolves_from_runtime_home(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime_root = Path(directory).resolve()
            config = runtime_root / "settings.toml"
            config.write_text('database_path = "private/jobs.sqlite3"\n', encoding="utf-8")
            environment = {"JOB_ASSISTANT_HOME": str(runtime_root), "JOB_ASSISTANT_CONFIG": "settings.toml"}
            with patch.dict(os.environ, environment, clear=True):
                settings = get_settings()
            self.assertEqual(settings.database_path, runtime_root / "private" / "jobs.sqlite3")

    def test_profile_filters_unknown_and_blank_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "profile.json"
            profile.write_text('{"first_name":"Ada", "password":"secret", "phone":"  "}', encoding="utf-8")
            self.assertEqual(load_profile(profile), {"first_name": "Ada"})
