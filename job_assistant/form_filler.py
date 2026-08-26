from __future__ import annotations

from playwright.async_api import Locator, Page


FIELD_SELECTORS: dict[str, tuple[str, ...]] = {
    "first_name": ("input[autocomplete='given-name']", "input[name*='first' i]", "input[id*='first' i]"),
    "last_name": ("input[autocomplete='family-name']", "input[name*='last' i]", "input[id*='last' i]"),
    "email": ("input[type='email']", "input[autocomplete='email']", "input[name*='email' i]"),
    "phone": ("input[type='tel']", "input[autocomplete='tel']", "input[name*='phone' i]"),
    "location": ("input[autocomplete='address-level2']", "input[name*='location' i]", "input[id*='location' i]"),
    "linkedin_url": ("input[name*='linkedin' i]", "input[id*='linkedin' i]"),
    "website_url": ("input[name*='website' i]", "input[name*='portfolio' i]", "input[id*='website' i]"),
}


async def fill_common_fields(page: Page, profile: dict[str, str]) -> list[str]:
    """Fill visible, empty text inputs only; excludes passwords, uploads, controls, and submit buttons."""
    filled: list[str] = []
    for field, value in profile.items():
        for selector in FIELD_SELECTORS.get(field, ()):
            locator = page.locator(selector)
            target = await _first_safe_empty_input(locator)
            if target is None:
                continue
            await target.fill(value)
            filled.append(field)
            break
    return filled


async def _first_safe_empty_input(locator: Locator) -> Locator | None:
    for index in range(await locator.count()):
        candidate = locator.nth(index)
        if not await candidate.is_visible() or not await candidate.is_editable():
            continue
        input_type = (await candidate.get_attribute("type") or "text").lower()
        if input_type in {"password", "file", "hidden", "checkbox", "radio", "submit", "button", "image"}:
            continue
        if await candidate.input_value():
            continue
        return candidate
    return None
