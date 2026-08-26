from __future__ import annotations

from pathlib import Path

from playwright.async_api import BrowserContext, Error as PlaywrightError, Page, Playwright, async_playwright


class PersistentBrowser:
    """A visible browser with a local, reusable profile owned by the user."""

    def __init__(self, user_data_dir: Path, browser_channel: str | None) -> None:
        self.user_data_dir = user_data_dir
        self.browser_channel = browser_channel
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None

    async def __aenter__(self) -> "PersistentBrowser":
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = await async_playwright().start()
        try:
            launch_options: dict[str, object] = {"headless": False}
            if self.browser_channel:
                launch_options["channel"] = self.browser_channel
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.user_data_dir), **launch_options
            )
        except Exception as exc:
            await self._playwright.stop()
            raise RuntimeError(
                f"Could not launch {self.browser_channel or 'Playwright Chromium'!r}. Install Chrome, or set "
                "JOB_ASSISTANT_BROWSER=chromium in .env to use Playwright Chromium."
            ) from exc
        return self

    async def active_page(self) -> Page:
        if not self._context:
            raise RuntimeError("Browser is not running.")
        pages = [page for page in self._context.pages if not page.is_closed()]
        if not pages:
            return await self._context.new_page()
        return next((page for page in reversed(pages) if page.url.startswith(("http://", "https://"))), pages[-1])

    async def new_page(self) -> Page:
        if not self._context:
            raise RuntimeError("Browser is not running.")
        return await self._context.new_page()

    async def __aexit__(self, *_: object) -> None:
        if self._context:
            try:
                await self._context.close()
            except PlaywrightError:
                # The user may close the visible window while the terminal is
                # waiting for input. It is already closed, so no cleanup action
                # remains for the assistant to perform.
                pass
        if self._playwright:
            await self._playwright.stop()
