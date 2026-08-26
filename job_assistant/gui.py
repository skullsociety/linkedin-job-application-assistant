"""Small Windows desktop interface for the local job assistant."""

from __future__ import annotations

import asyncio
import os
import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, scrolledtext, ttk

from .__main__ import _delete_generated_outputs, capture, match_latest_resume
from .browser import PersistentBrowser
from .config import Settings, get_settings
from .database import JobRepository
from .logging_config import configure_logging


class AssistantWindow:
    """Run the normal local workflow from a graphical window, not a shell."""

    def __init__(self, root: tk.Tk, settings: Settings) -> None:
        self.root = root
        self.settings = settings
        self.capture_stop: threading.Event | None = None
        self.login_done: threading.Event | None = None
        self.root.title("Linkedin Job Application Assistant")
        self.root.minsize(760, 540)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self._build()
        self.report("Ready. Your browser session and all files remain local on this computer.")

    def _build(self) -> None:
        container = ttk.Frame(self.root, padding=16)
        container.pack(fill="both", expand=True)
        ttk.Label(container, text="Linkedin Job Application Assistant", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(
            container,
            text="Use the buttons below instead of PowerShell. The app never signs in or submits an application for you.",
            wraplength=700,
        ).pack(anchor="w", pady=(2, 12))

        controls = ttk.Frame(container)
        controls.pack(fill="x")
        self.login_button = ttk.Button(controls, text="1. Log in to LinkedIn", command=self.start_login)
        self.login_button.grid(row=0, column=0, padx=(0, 8), pady=4, sticky="ew")
        self.finish_login_button = ttk.Button(controls, text="I have logged in", command=self.finish_login, state="disabled")
        self.finish_login_button.grid(row=0, column=1, padx=(0, 8), pady=4, sticky="ew")
        self.capture_button = ttk.Button(controls, text="2. Start auto-capture", command=self.start_capture)
        self.capture_button.grid(row=0, column=2, padx=(0, 8), pady=4, sticky="ew")
        self.stop_capture_button = ttk.Button(controls, text="Stop capture", command=self.stop_capture, state="disabled")
        self.stop_capture_button.grid(row=0, column=3, pady=4, sticky="ew")

        ttk.Button(controls, text="3. List saved jobs", command=self.list_jobs).grid(row=1, column=0, padx=(0, 8), pady=4, sticky="ew")
        ttk.Button(controls, text="4. Match newest resume", command=self.match_newest_resume).grid(row=1, column=1, padx=(0, 8), pady=4, sticky="ew")
        ttk.Button(controls, text="Open Excel tracker", command=self.open_tracker).grid(row=1, column=2, padx=(0, 8), pady=4, sticky="ew")

        ttk.Button(controls, text="Remove all saved data", command=self.confirm_clear).grid(row=2, column=0, padx=(0, 8), pady=(12, 4), sticky="ew")
        ttk.Label(controls, text="Capture and resume matching refresh the same Excel file automatically.").grid(row=2, column=1, columnspan=3, pady=(12, 4), sticky="w")
        for column in range(4):
            controls.columnconfigure(column, weight=1)

        ttk.Label(container, text="Activity", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(16, 4))
        self.activity = scrolledtext.ScrolledText(container, height=18, wrap="word", state="disabled", font=("Consolas", 9))
        self.activity.pack(fill="both", expand=True)

    def report(self, message: str) -> None:
        """Append a background-task message safely to the on-screen activity log."""
        self.root.after(0, self._append_message, message)

    def _append_message(self, message: str) -> None:
        self.activity.configure(state="normal")
        self.activity.insert("end", f"{message}\n")
        self.activity.see("end")
        self.activity.configure(state="disabled")

    def _run_background(self, name: str, action: Callable[[], None]) -> None:
        def runner() -> None:
            try:
                action()
            except Exception as exc:  # Keep a normal user workflow alive after a recoverable error.
                self.report(f"{name} failed: {exc}")

        threading.Thread(target=runner, daemon=True, name=name).start()

    def start_login(self) -> None:
        if self.capture_stop is not None:
            messagebox.showinfo("Capture in progress", "Stop auto-capture before opening a separate login browser.")
            return
        if self.login_done is not None:
            return
        self.login_done = threading.Event()
        self.login_button.configure(state="disabled")
        self.finish_login_button.configure(state="normal")

        async def open_login_browser() -> None:
            async with PersistentBrowser(self.settings.browser_user_data_dir, self.settings.browser_channel) as browser:
                page = await browser.new_page()
                await page.goto("https://www.linkedin.com/", wait_until="domcontentloaded")
                await page.bring_to_front()
                self.report("LinkedIn is open. Log in manually, then click ‘I have logged in’ here.")
                while self.login_done is not None and not self.login_done.is_set():
                    await asyncio.sleep(0.25)
            self.report("Login browser closed. Your signed-in browser session was saved locally.")

        def action() -> None:
            try:
                asyncio.run(open_login_browser())
            finally:
                self.root.after(0, self._login_finished)

        self._run_background("Login", action)

    def finish_login(self) -> None:
        if self.login_done is not None:
            self.login_done.set()

    def _login_finished(self) -> None:
        self.login_done = None
        self.login_button.configure(state="normal")
        self.finish_login_button.configure(state="disabled")

    def start_capture(self) -> None:
        if self.capture_stop is not None:
            return
        if self.login_done is not None:
            messagebox.showinfo("Login in progress", "Finish the login session first.")
            return
        self.capture_stop = threading.Event()
        self.capture_button.configure(state="disabled")
        self.stop_capture_button.configure(state="normal")

        def action() -> None:
            try:
                with JobRepository(self.settings.database_path) as repo:
                    asyncio.run(capture(repo, self.settings, None, None, stop_event=self.capture_stop, reporter=self.report))
            finally:
                self.root.after(0, self._capture_finished)

        self._run_background("Auto-capture", action)

    def stop_capture(self) -> None:
        if self.capture_stop is not None:
            self.capture_stop.set()
            self.report("Stopping auto-capture. The browser will close shortly.")

    def _capture_finished(self) -> None:
        self.capture_stop = None
        self.capture_button.configure(state="normal")
        self.stop_capture_button.configure(state="disabled")

    def list_jobs(self) -> None:
        def action() -> None:
            with JobRepository(self.settings.database_path) as repo:
                jobs = repo.list()
            if not jobs:
                self.report("No saved jobs yet.")
                return
            self.report(f"Saved jobs ({len(jobs)}):")
            for job in jobs:
                self.report(f"#{job.id} [{job.status}] {job.title} - {job.company} | score: {job.match_score if job.match_score is not None else 'not matched'}")

        self._run_background("List jobs", action)

    def match_newest_resume(self) -> None:
        """Match jobs with the newest PDF or DOCX in the local resumes folder."""
        def action() -> None:
            with JobRepository(self.settings.database_path) as repo:
                match_latest_resume(repo, None, self.settings, reporter=self.report)
            self.report("Matching is complete. The Excel tracker was refreshed automatically.")

        self._run_background("Resume matching", action)

    def open_tracker(self) -> None:
        if not self.settings.export_path.is_file():
            messagebox.showinfo("Tracker not found", "Export at least one job before opening the Excel tracker.")
            return
        os.startfile(self.settings.export_path)  # type: ignore[attr-defined]  # Windows-only desktop app.

    def confirm_clear(self) -> None:
        if not messagebox.askyesno(
            "Remove saved data",
            "Delete all saved job records, the Excel tracker, and generated resumes?\n\nYour browser login, profile, and source resume will stay untouched.",
        ):
            return

        def action() -> None:
            with JobRepository(self.settings.database_path) as repo:
                deleted = repo.delete_all()
            removed_files = _delete_generated_outputs(self.settings)
            self.report(f"Deleted {deleted} saved job(s) and {removed_files} generated file(s).")

        self._run_background("Clear saved data", action)

    def _close(self) -> None:
        if self.capture_stop is not None:
            self.capture_stop.set()
        if self.login_done is not None:
            self.login_done.set()
        self.root.destroy()


def main() -> None:
    """Open the desktop app using the local configuration and no shell window."""
    settings = get_settings()
    configure_logging(settings.log_path)
    root = tk.Tk()
    AssistantWindow(root, settings)
    root.mainloop()
