from __future__ import annotations

import json
from pathlib import Path


ALLOWED_FIELDS = {"first_name", "last_name", "email", "phone", "location", "linkedin_url", "website_url"}


def load_profile(path: Path) -> dict[str, str]:
    """Load only user-provided common application fields from a local JSON file."""
    if not path.is_file():
        raise FileNotFoundError(
            f"Profile not found: {path}. Copy profile.example.json to data/profile.json and add only fields you want filled."
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("Profile JSON is invalid.") from exc
    if not isinstance(raw, dict):
        raise ValueError("Profile JSON must contain an object.")
    return {key: str(value).strip() for key, value in raw.items() if key in ALLOWED_FIELDS and value is not None and str(value).strip()}
