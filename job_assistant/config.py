"""Application configuration with safe local-file and environment overrides."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True, slots=True)
class Settings:
    """Resolved local paths and visible-browser settings for the application."""

    database_path: Path
    export_path: Path
    log_path: Path
    browser_user_data_dir: Path
    browser_channel: str | None
    profile_path: Path
    tailored_resume_dir: Path
    tailored_resume_threshold: int
    resume_dir: Path
    resume_path: Path | None


def get_settings(config_path: Path | None = None) -> Settings:
    """Load defaults, then optional TOML settings, then local environment overrides."""
    runtime_root = _runtime_root()
    load_dotenv(runtime_root / ".env")
    configured_path = os.getenv("JOB_ASSISTANT_CONFIG", "").strip()
    selected_config = config_path or (
        _resolve_path(configured_path, runtime_root) if configured_path else runtime_root / "config.toml"
    )
    file_values = _read_config(selected_config)
    data_dir = _resolve_path(_value("data_dir", file_values, "data"), runtime_root)
    browser = _value("browser", file_values, "chrome")
    browser_channel = None if browser.casefold() == "chromium" else browser
    return Settings(
        database_path=_resolve_path(_value("database_path", file_values, str(data_dir / "jobs.sqlite3")), runtime_root),
        export_path=_resolve_path(_value("export_path", file_values, "exports/job_tracker.xlsx"), runtime_root),
        log_path=_resolve_path(_value("log_path", file_values, "logs/job_assistant.log"), runtime_root),
        browser_user_data_dir=_resolve_path(_value("browser_user_data_dir", file_values, str(data_dir / "browser-profile")), runtime_root),
        browser_channel=browser_channel,
        profile_path=_resolve_path(_value("profile_path", file_values, str(data_dir / "profile.json")), runtime_root),
        tailored_resume_dir=_resolve_path(_value("tailored_resume_dir", file_values, "exports/tailored_resumes"), runtime_root),
        tailored_resume_threshold=_score_threshold(_value("tailored_resume_threshold", file_values, "70")),
        resume_dir=_resolve_path(_value("resume_dir", file_values, "resumes"), runtime_root),
        resume_path=_optional_path(_value("resume_path", file_values, ""), runtime_root),
    )


def _read_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as config_file:
            values = tomllib.load(config_file)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"Invalid TOML configuration: {path}") from exc
    return values if isinstance(values, dict) else {}


def _value(name: str, file_values: dict[str, Any], default: str) -> str:
    environment_names = {
        "browser_user_data_dir": ("JOB_ASSISTANT_USER_DATA_DIR", "JOB_ASSISTANT_BROWSER_USER_DATA_DIR"),
        "browser": ("JOB_ASSISTANT_BROWSER",),
    }
    for environment_name in environment_names.get(name, (f"JOB_ASSISTANT_{name.upper()}",)):
        value = os.getenv(environment_name)
        if value is not None:
            return value.strip() or default
    value = file_values.get(name, default)
    return str(value).strip() or default


def _runtime_root() -> Path:
    configured = os.getenv("JOB_ASSISTANT_HOME", "").strip()
    return Path(configured).expanduser().resolve() if configured else ROOT


def _resolve_path(value: str, root: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else root / path


def _optional_path(value: str, root: Path) -> Path | None:
    return _resolve_path(value, root) if value.strip() else None


def _score_threshold(value: str) -> int:
    try:
        threshold = int(value)
    except ValueError as exc:
        raise ValueError("tailored_resume_threshold must be a whole number from 0 to 100.") from exc
    if not 0 <= threshold <= 100:
        raise ValueError("tailored_resume_threshold must be from 0 to 100.")
    return threshold
