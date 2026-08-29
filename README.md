# LinkedIn Job Application Assistant

The recommended interface is now a private Chrome extension plus a local Python companion. Chrome reads only the LinkedIn job page you already opened and signed into; the companion keeps the existing SQLite tracker, Excel export, resume matching, cover letters, and tailored PDFs on your computer. The previous Python + Playwright launcher remains available as a fallback.

This is an independent open-source project. It is not affiliated with, endorsed by, or sponsored by LinkedIn.

## Requirements

- Windows, macOS, or Linux
- [Node.js 18 or newer](https://nodejs.org/) (provides the installer and launcher)
- [Python 3.11 or newer](https://www.python.org/downloads/)
- Google Chrome for automatic native-helper startup. Other Chromium browsers can load the unpacked extension, but require their own native-host registration or a manually started companion.

## Install from a GitHub clone

```powershell
https://github.com/skullsociety/linkedin-job-application-assistant
cd linkedin-job-application-assistant
npm install
npm run setup
npm run chrome:install
npm run extension:path
```

`npm run chrome:install` registers a restricted native helper for the current operating-system user. `npm run extension:path` prints the exact folder to select in Chrome. Open `chrome://extensions`, enable **Developer mode**, choose **Load unpacked**, and select that folder. From then on, opening Chrome starts the companion silently when the extension needs it; `npm start` remains a visible troubleshooting option.

For a GitHub clone on Windows, `Setup Linkedin Job Assistant.bat` performs the one-time application and Chrome-integration setup. The other `.bat` and `.vbs` launchers are GitHub-clone-only diagnostic fallbacks; they discover the project folder and its private Python environment dynamically and contain no username-specific or fixed installation path. They are not included in the npm package.

## Install from npm

Once this package has been published to npm, users can install it globally:

```powershell
npm install --global linkedin-job-application-assistant
linkedin-job-assistant setup
linkedin-job-assistant install-chrome-host
linkedin-job-assistant extension-path
```

A local project install also works with `npx linkedin-job-assistant <command>`. The npm package name is not reserved until it is successfully published, so verify it before announcing the final install command.

Chrome does not allow an npm package to silently install or enable an extension. The safe public options are **Load unpacked** using the printed extension path, or publishing the extension separately through the Chrome Web Store for one-click browser installation. The native-host registration permits only this extension's stable ID and can only request that the already-installed local companion start.

### Automatic startup with Chrome

The normal workflow does not require a `.bat` file. When a Chrome profile containing the extension starts, or when an extension request finds the companion offline, the extension asks Chrome's registered native helper to start it silently. The helper accepts only the `start` action; it cannot install packages, run arbitrary commands, read a LinkedIn password, or submit an application.

Registration is per operating-system user and per computer. Run it again after moving a GitHub clone to a different folder or computer:

```powershell
npm run chrome:install
```

Remove only the Chrome integration, without deleting jobs or resumes, with `npm run chrome:remove`. For a global npm installation, use `linkedin-job-assistant install-chrome-host` and `linkedin-job-assistant remove-chrome-host`.

### Optional Windows-login startup fallback

Automatic startup is an explicit choice and is not added during `npm install`:

```powershell
# In a GitHub clone
npm run autostart:install

# In a global npm installation
linkedin-job-assistant install-autostart
```

This alternative starts the companion when the current Windows user signs in, even when Chrome is not open. Chrome-triggered startup is the recommended default. Remove the Windows-login task with `npm run autostart:remove` or `linkedin-job-assistant remove-autostart`.

### Portable private data

- A GitHub clone keeps `data/`, `exports/`, `logs/`, `resumes/`, `.venv`, and `config.toml` inside the cloned folder. They are excluded from Git and npm publishing.
- An npm installation keeps those private files outside `node_modules` in the current user's application-data folder, so a package update does not overwrite them.
- Set `JOB_ASSISTANT_HOME` to an absolute folder if you want a different private-data location.
- If Python is installed but is not discoverable from the command line, set `JOB_ASSISTANT_PYTHON` to the full Python executable path before running setup.
- After moving a clone to another computer, run `npm run setup` and `npm run chrome:install` again. Native-host registration and Windows scheduled tasks do not travel with the project folder.

### Portable launcher commands

| Command | Purpose |
| --- | --- |
| `setup` | Create the private folders and Python environment, then install the declared Python packages. |
| `start` | Start the local companion in the current terminal. |
| `dashboard` | Start the companion in the background and open the local dashboard. |
| `doctor` | Show resolved paths, setup state, and whether the companion is running. |
| `extension-path` | Print the stable folder that Chrome should load. |
| `chrome-extension-id` | Print the stable extension ID allowed to use the native helper. |
| `install-chrome-host` | Register automatic companion startup when Chrome needs it. |
| `remove-chrome-host` | Remove Chrome-triggered startup without deleting user data. |
| `install-autostart` | Register automatic companion startup for the current Windows user. |
| `remove-autostart` | Remove automatic startup without deleting user data. |

## Safety boundaries

- It does **not** handle logins, CAPTCHAs, anti-bot checks, or access controls.
- It never reads, saves, or enters a LinkedIn password. You sign in yourself in a visible browser window.
- It does **not** crawl job boards or automatically submit applications.
- A final submission is always performed manually by you in the browser. `approve-submit` only records your approval in the local database.

## Chrome extension workflow (recommended)

This is intentionally a **hybrid** design rather than a browser-only extension. A browser-only rewrite would duplicate the local PDF/DOCX, SQLite, resume-generation, and Excel work; the companion keeps those tested functions and lets Chrome be the interface in your normal signed-in session.

1. Put your newest PDF or DOCX resume directly in `resumes/`. The newest file is used automatically.
2. Complete the one-time Chrome integration with `npm run chrome:install`. You do not open a `.bat` file during normal use.
3. In your normal Chrome, open `chrome://extensions`, enable **Developer mode**, select **Load unpacked**, and choose the [extension](extension) folder. If an older unpacked copy is present from before version 1.2.0, remove that copy first so Chrome adopts the new stable extension ID.
4. Pin **LinkedIn Job Application Assistant**. On first use, open **Edit safe fill profile** and enter only the contact values you want it to fill. It imports the existing `data/profile.json` contact fields when that file already exists; it never imports or accepts a password.
5. Open a LinkedIn job that you have access to, click **Show more** if LinkedIn shows it, then scroll until **About the job** is visible. With the default Auto-capture setting, the expanded visible description saves once. You can turn this off and use **Capture this job** in the side panel instead.
6. The record is written to `data/jobs.sqlite3` immediately. Resume matching and a tailored PDF run in the background, and `exports/job_tracker.xlsx` is overwritten with the updated tracker. Close the Excel workbook before capturing another job so Windows can replace it.

The side panel shows the current listing, score, recognized matching/missing technical skills, recommendation, and a tailored-resume link when one was generated. **Manual application review** only shows instructions, fills supported empty contact fields after you explicitly click its button, and generates review-only text drafts. It never clicks Apply, Save, declarations, Continue, or Submit.

### Workday and SuccessFactors applications opened from LinkedIn

The extension also supports the common external Workday address format `*.myworkdayjobs.com` and SuccessFactors address format `*.successfactors.com`. After you have saved your safe fill profile, it fills only empty, supported contact fields when either application page appears. This includes first name, last name, email, phone, location, LinkedIn URL, and website/portfolio URL when the page exposes a clear matching field.

It intentionally does **not** fill passwords, verification codes, national IDs, citizenship, demographic questions, salary expectations, start dates, checkboxes, radio buttons, declarations, document uploads, or any control that advances or submits an application. Autofill is completely disabled on account-creation, sign-in, password, password-reset, and verification pages — including the email field. Create and verify Workday or SuccessFactors accounts yourself. Review each highlighted field yourself before continuing. If a Workday field is unclear or pre-filled, it is left unchanged.

Reload the extension from `chrome://extensions` after this update so Chrome accepts the additional Workday and SuccessFactors site permissions.

Keyboard shortcuts while a LinkedIn job page has focus:

- `Ctrl+Q` — capture the expanded visible job description.
- `Ctrl+M` — open the local dashboard.

There is deliberately no batch result-page scraper or automatic tab opener for LinkedIn. Capturing only the listing you opened avoids broad collection behaviour, lowers the chance of a LinkedIn session restriction, and preserves the original visible-page-only boundary.

### If automatic companion startup does not connect

1. Run `npm run doctor`. **Chrome-triggered startup** should say `Installed`.
2. If it is not installed, run `npm run chrome:install` again.
3. In Chrome, open `chrome://extensions` and click the reload icon on **LinkedIn Job Application Assistant**. Chrome does not use new extension files until you reload it.
4. Reopen the extension side panel. Its connection line should change to **Connected on this computer**.

If Chrome displays a native-host error, users of a GitHub clone can double-click [Start Linkedin Chrome Companion.bat](<Start Linkedin Chrome Companion.bat>) as a visible diagnostic fallback. Users of the npm package should run `linkedin-job-assistant start` instead. Either command should display `Dashboard: http://127.0.0.1:8766/`. You can also open `http://127.0.0.1:8766/` directly whenever the companion is running.

## Python-only developer setup

The Node-based setup above is recommended for normal users. Contributors who want to run the Python package directly can instead:

1. Install Python 3.11+.
2. Create and activate an environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   playwright install chromium
   ```

3. Copy `config.example.toml` to `config.toml` to change local paths or choose Chrome/Chromium. You can also copy `.env.example` to `.env` for environment-based overrides. Both files are ignored by Git.

Use an alternate configuration file with:

```powershell
python -m job_assistant --config C:\path\to\local-settings.toml list
```

## First-time LinkedIn login

1. Run `python -m job_assistant login`.
2. A visible Chrome window opens using `data/browser-profile`; enter your LinkedIn email, password, and any verification challenge **yourself** in that window.
3. When LinkedIn is fully signed in, return to the terminal and press Enter. The browser closes, but the profile directory keeps the session for later commands.

Never copy a personal Chrome profile into this folder, share this folder, or commit it. To reset the saved session, close the assistant and delete `data/browser-profile` yourself.

## Typical workflow

```powershell
# Opens LinkedIn Jobs and keeps that browser window open for a capture session.
# Scroll to About the job; each fully visible description is saved and matched automatically once.
# The same exports/job_tracker.xlsx file is refreshed after every newly saved job.
# Keep that workbook closed while capturing so Excel does not lock it.
# When a match is at or above your configured threshold, a tailored PDF is created automatically.
# Press Ctrl+C in the terminal when you are done.
python -m job_assistant capture

# List saved jobs. Capture and resume matching refresh the same tracker automatically.
python -m job_assistant list

# Match the newest PDF or DOCX in the resumes folder. For every score at or above your configured threshold, a tailored PDF is created locally.
python -m job_assistant match-latest-resume

# Run the approval-gated, non-submitting application flow for a saved job.
python -m job_assistant apply 1

# Print a short tailored cover-letter draft, or save it with --output.
python -m job_assistant cover-letter 1 C:\path\to\resume.docx --output exports\cover_letter_1.txt

# Open a saved job's application page and keep the browser open for manual review.
python -m job_assistant prepare 1

# Record that you approved the application for manual submission.
python -m job_assistant approve-submit 1 --confirm
```

`prepare` never clicks a submit control. Review every field and complete any challenge yourself. `approve-submit` records approval in your tracker; when you are ready, click the website's final submit button manually.

## Quick launcher for GitHub clones (Windows)

These launcher files are included in a GitHub clone but not in the npm package. For a desktop window with no PowerShell or command window, double-click `Launch Linkedin Job Application Assistant.vbs` in the cloned folder. It opens the graphical launcher for logging in, auto-capturing, listing jobs, matching your resume, opening Excel, and clearing saved data.

`job_assistant.bat` remains available if you prefer the original text menu, or run it in PowerShell:

```powershell
.\job_assistant.bat
```

The menu lets you log in once, capture jobs, match the default resume, and begin the manual application flow. Capture and matching automatically refresh the tracker. It never enters credentials or submits an application.

Option 6 asks for a `[Y/N]` confirmation before clearing all saved job records, the generated Excel tracker, and tailored resumes. It does not delete your browser login session, profile, configuration, or source resume.

For an npm installation, use the packaged commands instead:

```powershell
linkedin-job-assistant start
linkedin-job-assistant dashboard
linkedin-job-assistant doctor
```

## Local data and privacy

- `data/` contains the SQLite tracker, browser session, and optional application profile.
- `exports/` can contain personally tailored trackers and cover letters.
- `logs/`, `.env`, `config.toml`, PDFs, DOCX files, and XLSX files are ignored by Git.
- Never put passwords in `data/profile.json`, `config.toml`, or `.env`.

## Data and logs

- SQLite database: `data/jobs.sqlite3`
- Excel exports: `exports/`
- Logs: `logs/job_assistant.log`

The database stores the stable LinkedIn job ID, title, company, company URL, job URL, application URL and method, platform, internal listing source (`linkedin` by default), location, salary (when visible), full description, workplace type, employment type, seniority, applicant count (when visible), posting date, description fingerprint, first/last seen timestamps, view count, match data, notes, scheduled follow-up date, status, priority/tags placeholders, and user-confirmed application and follow-up states with timestamps. The scraper reads only content rendered in the page you manually opened while signed in.

The internal listing source is intentionally omitted from the local web dashboard, which shows only the useful working columns: position, capture date, match, Applied, Followed up, tailored resume, and delete. Change **Applied?** between **Not applied** and **Applied**, or **Followed up?** between **No** and **Yes**, to store each user-confirmed action and its timestamp. The database retains an event history for both actions so later dashboard metrics are not inferred from merely viewing a listing. In future AWS queries, `jobs.source` identifies where a listing came from, while `job_events.source` identifies which local component recorded an event. AWS synchronization is not implemented yet.

The Excel export is a formatted `Job Tracker` workbook with these columns: Date, Platform, Company, Role, URL, Location, Salary, Match Score, Skills Missing for 100% Match, Status, Notes, Follow-up Date, and Followed Up. The missing-skills column lists job skills not detected in your resume, after matching has run. URLs are unique in SQLite and are de-duplicated again during export as a safeguard. LinkedIn search-results URLs are converted to their stable job-ID URLs, so opening the same listing again with a new tracking token updates one record instead of creating a duplicate. Set a scheduled follow-up date with `update ID --follow-up-date YYYY-MM-DD`; the dashboard's separate **Followed up?** control records whether you completed it.

## Resume matching

`match-resume` reads a local, text-based PDF or DOCX resume and compares it locally with each saved job description. It never uploads the resume. It records a 0-100 skills-coverage score, matching skills, missing skills, a plain-language reason, and one recommendation: `apply`, `skip`, or `review manually`.

The score is intentionally a transparent screen, not a hiring prediction. It compares objective, technical skills found in the job description with skills found in your resume. Soft skills such as leadership, communication, teamwork, stakeholder management, and customer service do not affect the score. Closely related ETL terms (for example data pipelines, transformation, quality, analytics, and engineering) are treated as one capability, so they do not appear as separate missing skills. Sparse descriptions and descriptions with fewer than two recognized skills are always marked `review manually`.

When a job scores at or above the configured `tailored_resume_threshold` (70% in your local `config.toml`), matching creates `exports/tailored_resumes/tailored_resume_<company>_<role>_<id>.pdf`. The PDF prioritizes matching skills while retaining the source resume's newest-first experience order. Only a clearly unrelated role without matching-skill evidence may move below related experience. It does not invent experience, employers, certifications, or achievements; review every draft before using it.

Put PDFs or DOCX resumes directly in `resumes/`. Automatic capture and `match-latest-resume` always use the most recently modified supported file in that folder. You can retain older versions there; the newest file wins. `resume_path` remains available only as an optional fallback for older setups.

## Cover letters

`cover-letter ID RESUME.pdf|RESUME.docx` creates a short local draft from the saved job description and your resume. It only states experience with skills detected in both texts and does not add certifications, employers, accomplishments, or any other unverified claims. Review and personalize the draft before using it.

## Application flow

1. Copy `profile.example.json` to `data/profile.json`, adding only the common fields you explicitly want the assistant to fill. This file is ignored by Git. Never put passwords in it.
2. Run `python -m job_assistant apply ID`. The assistant opens the matched job and shows its saved details, score, matching/missing skills, and recommendation.
3. Answer the continue prompt. If you continue, open the site's application form yourself and complete any verification manually.
4. The assistant fills only visible, currently empty common text inputs (name, email, phone, location, LinkedIn URL, and website URL) from your profile. It does not fill passwords, uploads, checkboxes, radio buttons, or submission controls.
5. It displays local draft answers for visible text-area questions without entering them. Review, edit, or ignore them yourself.
6. It waits for the exact word `READY`, records the manual-submission approval, and stops. It never clicks the website's final submit button.

## Commands

```text
capture [--score 0..100] [--notes TEXT]
login
match-resume RESUME.pdf|RESUME.docx [--job ID]
match-latest-resume [--job ID]
apply ID
cover-letter ID RESUME.pdf|RESUME.docx [--output PATH]
list [--status STATUS]
update ID [--score 0..100] [--notes TEXT] [--status STATUS]
prepare ID
approve-submit ID --confirm
export [--output PATH]
```

`capture` works on LinkedIn's full job page and its current search-results detail panel. Before pressing Enter, scroll until the **About the job** description is visible. It saves that rendered description and writes the Notes field with the description plus every recognized skill mentioned in it. If LinkedIn or another site asks for verification or blocks the page, it pauses for you to resolve that manually; it does not attempt to interact with the challenge.

## Development checks

```powershell
python -m unittest discover -s tests -v
python -m compileall job_assistant companion
```
