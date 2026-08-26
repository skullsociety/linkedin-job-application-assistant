(() => {
  "use strict";
  if (globalThis.__linkedInJobAssistantLoaded) return;
  globalThis.__linkedInJobAssistantLoaded = true;

  let autoCaptureEnabled = true;
  let autoCaptureUrl = "";
  let storedProfile = {};
  let scheduled = 0;
  let workdayScheduled = 0;
  let accountScreenNotice = "";

  const clean = (value) => (value || "").replace(/\s+/g, " ").trim();
  const visible = (element) => Boolean(element && element.getClientRects().length && getComputedStyle(element).visibility !== "hidden");
  const visibleText = (element) => visible(element) ? clean(element.innerText) : "";

  function isLinkedInHostname(hostname) {
    const value = (hostname || "").toLowerCase().replace(/\.$/, "");
    return value === "linkedin.com" || value.endsWith(".linkedin.com");
  }

  function canonicalJobUrl() {
    const url = new URL(location.href);
    if (!isLinkedInHostname(url.hostname)) return "";
    const direct = url.pathname.match(/\/jobs\/view\/(\d+)/);
    const id = direct?.[1] || url.searchParams.get("currentJobId");
    return id && /^\d+$/.test(id) ? `https://www.linkedin.com/jobs/view/${id}/` : "";
  }

  function onJobPage() {
    return Boolean(canonicalJobUrl());
  }

  function onWorkdayPage() {
    return location.hostname.endsWith(".myworkdayjobs.com");
  }

  function onSuccessFactorsPage() {
    return location.hostname.endsWith(".successfactors.com");
  }

  function externalApplicationPlatform() {
    if (onWorkdayPage()) return "Workday";
    if (onSuccessFactorsPage()) return "SuccessFactors";
    return "";
  }

  // Account, sign-in, password, and verification pages are never application
  // forms. Do not send even contact data to them, whether autofill was
  // scheduled by the page or requested from the side panel.
  function isAccountOrVerificationScreen() {
    if (!externalApplicationPlatform()) return false;
    if ([...document.querySelectorAll("input[type='password']")].some(visible)) return true;

    const pageHeading = clean(
      [...document.querySelectorAll("h1, h2, h3, [role='heading']")]
        .filter(visible)
        .map((element) => element.innerText)
        .join(" "),
    ).toLowerCase();
    const markers = [
      "create account", "create your account", "sign in", "log in",
      "forgot password", "reset password", "change password", "password requirements",
      "account recovery", "verify your email", "email verification",
      "verification code", "one-time passcode", "one-time code", "two-factor", "multi-factor",
    ];
    return markers.some((marker) => pageHeading.includes(marker));
  }

  function firstText(selectors) {
    for (const selector of selectors) {
      for (const element of document.querySelectorAll(selector)) {
        const text = visibleText(element);
        if (text) return text;
      }
    }
    return "";
  }

  function descriptionContainer() {
    const candidates = [
      "#job-details",
      ".jobs-description-content__text",
      ".jobs-description__content",
      ".jobs-box__html-content",
      "[class*='jobs-description']",
    ];
    for (const selector of candidates) {
      for (const element of document.querySelectorAll(selector)) {
        const text = visibleText(element);
        if (/about the job/i.test(text) || text.length > 100) return element;
      }
    }
    return null;
  }

  function aboutText() {
    const container = descriptionContainer();
    const text = visibleText(container);
    if (text) {
      const lines = text.split(/\n+/).map(clean).filter(Boolean);
      const about = lines.findIndex((line) => line.toLowerCase() === "about the job");
      return (about >= 0 ? lines.slice(about + 1) : lines).join("\n").trim();
    }
    const lines = (document.body?.innerText || "").split(/\n+/).map(clean).filter(Boolean);
    const start = lines.findIndex((line) => line.toLowerCase() === "about the job");
    if (start < 0) return "";
    const stop = new Set(["meet the hiring team", "job poster", "about the company", "similar jobs", "people also viewed", "recommended for you"]);
    const description = [];
    for (const line of lines.slice(start + 1)) {
      if (stop.has(line.toLowerCase())) break;
      description.push(line);
    }
    return description.join("\n").trim();
  }

  function hasVisibleShowMore() {
    const container = descriptionContainer();
    if (!container) return false;
    return [...container.querySelectorAll("button, a")].some((element) => visible(element) && /^show more$/i.test(clean(element.textContent)));
  }

  function aboutHeadingInView() {
    const heading = [...document.querySelectorAll("h2, h3, span, strong")]
      .find((element) => visible(element) && clean(element.textContent).toLowerCase() === "about the job");
    if (!heading) return false;
    const rect = heading.getBoundingClientRect();
    return rect.bottom >= 0 && rect.top <= innerHeight;
  }

  const NON_JOB_TITLES = new Set(["easy apply", "apply", "save", "job details", "additional questions", "application"]);

  function usableJobTitle(value) {
    const title = clean(value);
    return Boolean(title && title.length <= 180 && !NON_JOB_TITLES.has(title.toLowerCase()));
  }

  function jobHeaderText(selectors, predicate = () => true) {
    for (const selector of selectors) {
      for (const element of document.querySelectorAll(selector)) {
        // An Easy Apply dialog can contain headings that look like job headings.
        if (element.closest("[role='dialog'], .artdeco-modal")) continue;
        const value = visibleText(element);
        if (value && predicate(value)) return value;
      }
    }
    return "";
  }

  function headerLines() {
    const card = document.querySelector(".job-details-jobs-unified-top-card");
    const cardTitle = jobHeaderText([
      ".job-details-jobs-unified-top-card__job-title",
      ".job-details-jobs-unified-top-card h1",
    ], usableJobTitle);
    const title = cardTitle || jobHeaderText([
      "[data-test-id='job-title']",
      "[data-view-name*='job-details'] h1",
      "main h1",
      "h1",
    ], usableJobTitle);
    const company = jobHeaderText([
      ".job-details-jobs-unified-top-card__company-name a",
      ".job-details-jobs-unified-top-card__company-name",
      "[data-test-id='company-name']",
      "[data-view-name*='job-details'] a[href*='/company/']",
      "a[href*='/company/']",
    ]);
    const metadata = card ? firstText([".job-details-jobs-unified-top-card__primary-description-container", ".job-details-jobs-unified-top-card__primary-description"])
      : jobHeaderText(["[data-view-name*='job-details'] [class*='primary-description']"]);
    if (title && company) return { title, company, metadata };
    const lines = (document.body?.innerText || "").split(/\n+/).map(clean).filter(Boolean);
    const titleIndex = title ? lines.indexOf(title) : -1;
    const fallbackTitle = title || lines.find((line, index) => usableJobTitle(line) && index > 0 && /(?:ago|applicants|clicked apply|reposted)/i.test(lines[index + 1] || "")) || "";
    const index = titleIndex >= 0 ? titleIndex : lines.indexOf(fallbackTitle);
    return { title: fallbackTitle, company: company || (index > 0 ? lines[index - 1] : ""), metadata };
  }

  function firstVisibleLink(selectors) {
    for (const selector of selectors) {
      for (const element of document.querySelectorAll(selector)) {
        if (!visible(element) || !element.href) continue;
        try {
          const url = new URL(element.href, location.href);
          if (url.protocol === "http:" || url.protocol === "https:") return url.href;
        } catch (_error) {
          // Ignore incomplete links while LinkedIn is rendering the listing.
        }
      }
    }
    return "";
  }

  function applicationDetails() {
    const controls = [...document.querySelectorAll(
      ".job-details-jobs-unified-top-card button, .job-details-jobs-unified-top-card a, [data-view-name*='job-details'] button, [data-view-name*='job-details'] a",
    )].filter((element) => visible(element) && /\b(?:easy\s+apply|apply)\b/i.test(clean(element.innerText || element.getAttribute("aria-label"))));
    const easyApply = controls.find((element) => /easy\s+apply/i.test(clean(element.innerText || element.getAttribute("aria-label"))));
    const control = easyApply || controls[0];
    let applicationUrl = "";
    if (control?.href) {
      try {
        const parsed = new URL(control.href, location.href);
        if (parsed.protocol === "http:" || parsed.protocol === "https:") applicationUrl = parsed.href;
      } catch (_error) {
        // Keep the method even when the page exposes an incomplete application URL.
      }
    }
    return {
      application_method: easyApply ? "Easy Apply" : control ? "External website" : "Not shown",
      application_url: applicationUrl,
    };
  }

  function firstKnownValue(text, values) {
    const normalized = clean(text).toLowerCase();
    return values.find((value) => new RegExp(`(?:^|[^a-z])${value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/-/g, "[-‑–— ]")}(?:$|[^a-z])`, "i").test(normalized)) || "";
  }

  function extractJob() {
    const url = canonicalJobUrl();
    if (!url) throw new Error("Open a full LinkedIn job-detail page before capturing.");
    const pageText = clean(document.body?.innerText);
    if (/(security verification|verify your identity|unusual activity|captcha|robot check)/i.test(pageText)) {
      throw new Error("LinkedIn is asking for verification. Complete it manually; the assistant will not interact with it.");
    }
    const { title, company, metadata } = headerLines();
    const description = aboutText();
    if (!title || !company) throw new Error("The job title or company is not visible yet. Wait for the listing to finish loading.");
    if (hasVisibleShowMore()) throw new Error("Click Show more in About the job before capturing so the full visible description is stored.");
    if (!description || description.length < 80) throw new Error("Scroll to About the job and expand its description before capturing.");
    const lines = [metadata, pageText].filter(Boolean).join(" · ");
    const location = (metadata.split("·")[0] || "").trim() || "";
    const workplace = lines.match(/\b(On-site|Hybrid|Remote)\b/i)?.[1] || "";
    const applicants = lines.match(/(?:Over\s+)?[\d,]+\s+(?:people\s+)?(?:clicked apply|applicants?)/i)?.[0] || "";
    const posting = lines.match(/(?:Reposted\s+)?\d+\s+(?:minute|hour|day|week|month)s?\s+ago/i)?.[0] || "";
    const salary = lines.match(/(?:S\$|SGD\s?)\s?[\d,]+(?:\s*[-–]\s*(?:S\$|SGD\s?)?[\d,]+)?(?:\s*(?:a year|per year|monthly|\/yr))?/i)?.[0] || "";
    const linkedinJobId = url.match(/\/jobs\/view\/(\d+)/)?.[1] || "";
    const companyUrl = firstVisibleLink([
      ".job-details-jobs-unified-top-card__company-name a[href*='/company/']",
      "[data-test-id='company-name'] a[href*='/company/']",
      "[data-view-name*='job-details'] a[href*='/company/']",
    ]);
    const application = applicationDetails();
    const employmentType = firstKnownValue(pageText, ["Full-time", "Part-time", "Contract", "Temporary", "Internship", "Volunteer"]);
    const seniorityLevel = firstKnownValue(pageText, ["Internship", "Entry level", "Associate", "Mid-Senior level", "Director", "Executive"]);
    return {
      title,
      company,
      url,
      linkedin_job_id: linkedinJobId,
      company_url: companyUrl,
      application_url: application.application_url,
      application_method: application.application_method,
      location,
      salary,
      workplace_type: workplace,
      employment_type: employmentType,
      seniority_level: seniorityLevel,
      applicant_count: applicants,
      posting_date: posting,
      job_description: description,
    };
  }

  function showStatus(message, kind = "pending") {
    let toast = document.querySelector("#linkedin-job-assistant-toast");
    if (!toast) {
      toast = document.createElement("div");
      toast.id = "linkedin-job-assistant-toast";
      toast.setAttribute("role", "status");
      toast.style.cssText = "position:fixed;right:24px;bottom:24px;z-index:2147483647;max-width:360px;padding:13px 17px;border-radius:12px;color:#fff;font:600 14px/1.4 Segoe UI,sans-serif;box-shadow:0 12px 32px rgba(0,0,0,.25)";
      document.documentElement.appendChild(toast);
    }
    toast.textContent = message;
    toast.style.background = kind === "success" ? "#057642" : kind === "error" ? "#b42318" : "#0a66c2";
    toast.style.display = "block";
    clearTimeout(globalThis.__linkedinAssistantToast);
    globalThis.__linkedinAssistantToast = setTimeout(() => { toast.style.display = "none"; }, kind === "error" ? 6500 : 4000);
  }

  function fillSafeFields(profile) {
    if (isAccountOrVerificationScreen()) {
      throw new Error("Autofill is disabled on account-creation, sign-in, password, and verification screens.");
    }
    const aliases = {
      first_name: ["first name", "given name", "firstname", "given-name"],
      last_name: ["last name", "family name", "lastname", "family-name"],
      email: ["email", "e-mail"],
      phone: ["phone", "mobile", "telephone", "tel"],
      location: ["location", "city", "address-level2"],
      linkedin_url: ["linkedin", "linkedin url"],
      website_url: ["website", "portfolio", "personal site"],
    };
    const disallowed = new Set(["password", "file", "hidden", "checkbox", "radio", "submit", "button", "image", "date"]);
    const filled = [];
    for (const [field, value] of Object.entries(profile || {})) {
      if (!value || !aliases[field]) continue;
      for (const input of document.querySelectorAll("input, textarea")) {
        if (!visible(input) || input.disabled || input.readOnly || clean(input.value)) continue;
        const type = (input.type || "text").toLowerCase();
        if (disallowed.has(type)) continue;
        const identity = inputIdentity(input);
        if (!aliases[field].some((alias) => identity.includes(alias))) continue;
        setNativeValue(input, value);
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
        input.style.outline = "3px solid rgba(5,118,66,.25)";
        input.style.background = "#edfff4";
        filled.push(field);
        break;
      }
    }
    return [...new Set(filled)];
  }

  function inputIdentity(input) {
    const label = document.querySelector(`label[for="${CSS.escape(input.id || "-")}"]`)?.innerText || "";
    const labelledBy = (input.getAttribute("aria-labelledby") || "").split(/\s+/)
      .map((id) => document.getElementById(id)?.innerText || "").join(" ");
    const contextText = clean(input.closest("[data-automation-id], [data-automation-widget], li")?.innerText || "");
    // A large enclosing Workday form can contain labels for every field. Ignore
    // that broad text rather than risking a contact value in the wrong field.
    const fieldText = contextText.length <= 240 ? contextText : "";
    return clean([input.name, input.id, input.autocomplete, input.getAttribute("aria-label"), input.placeholder, label, labelledBy, fieldText].filter(Boolean).join(" ")).toLowerCase();
  }

  function setNativeValue(input, value) {
    const prototype = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
    if (setter) setter.call(input, value);
    else input.value = value;
  }

  function customQuestions() {
    const questions = [];
    for (const textarea of document.querySelectorAll("textarea")) {
      if (!visible(textarea)) continue;
      const label = document.querySelector(`label[for="${CSS.escape(textarea.id || "-")}"]`)?.innerText || "";
      const question = clean(textarea.getAttribute("aria-label") || textarea.placeholder || label || textarea.closest("fieldset, div")?.innerText || "").slice(0, 500);
      if (question) questions.push(question);
    }
    return [...new Set(questions)];
  }

  function scheduleAutoCapture() {
    clearTimeout(scheduled);
    scheduled = setTimeout(async () => {
      if (!autoCaptureEnabled || !onJobPage()) return;
      const url = canonicalJobUrl();
      if (!url || url === autoCaptureUrl || !aboutHeadingInView() || hasVisibleShowMore()) return;
      try {
        const job = extractJob();
        autoCaptureUrl = job.url;
        showStatus("About the job is visible. Capturing this listing locally…");
        const response = await chrome.runtime.sendMessage({ type: "AUTO_CAPTURE_LINKEDIN_JOB" });
        if (!response?.ok) {
          autoCaptureUrl = "";
          showStatus(response?.error || "The visible job could not be captured.", "error");
        }
      } catch (_error) {
        // It is normal for a page to be incomplete while LinkedIn renders it.
      }
    }, 550);
  }

  function scheduleExternalApplicationAutofill() {
    const platform = externalApplicationPlatform();
    if (!platform) return;
    clearTimeout(workdayScheduled);
    workdayScheduled = setTimeout(() => {
      if (isAccountOrVerificationScreen()) {
        if (accountScreenNotice !== location.href) {
          accountScreenNotice = location.href;
          showStatus(`${platform}: autofill is disabled on this account or password screen.`, "pending");
        }
        return;
      }
      accountScreenNotice = "";
      const filled = fillSafeFields(storedProfile);
      if (filled.length) {
        showStatus(`${platform}: filled only empty contact fields (${filled.join(", ")}). Review them before continuing.`, "success");
      }
    }, 550);
  }

  async function initializeProfile() {
    try {
      const response = await chrome.runtime.sendMessage({ type: "GET_LINKEDIN_PROFILE" });
      if (response?.ok) {
        storedProfile = response.profile || {};
        autoCaptureEnabled = response.autoCapture !== false;
      }
    } catch (_error) {
      // The page remains manual-only if Chrome is still starting the extension.
    }
    scheduleAutoCapture();
    scheduleExternalApplicationAutofill();
  }

  initializeProfile();
  addEventListener("scroll", scheduleAutoCapture, { passive: true });
  new MutationObserver(() => { scheduleAutoCapture(); scheduleExternalApplicationAutofill(); }).observe(document.documentElement, { childList: true, subtree: true });

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    try {
      if (message?.type === "EXTRACT_LINKEDIN_JOB") {
        sendResponse({ ok: true, job: extractJob() });
        return false;
      }
      if (message?.type === "SHOW_ASSISTANT_STATUS") {
        showStatus(String(message.message || ""), message.kind || "pending");
        sendResponse({ ok: true });
        return false;
      }
      if (message?.type === "FILL_LINKEDIN_SAFE_FIELDS") {
        const filled = fillSafeFields(message.profile || {});
        sendResponse({ ok: true, filled });
        return false;
      }
      if (message?.type === "LINKEDIN_PROFILE_UPDATED") {
        storedProfile = message.profile || {};
        autoCaptureEnabled = message.autoCapture !== false;
        scheduleAutoCapture();
        scheduleExternalApplicationAutofill();
        sendResponse({ ok: true });
        return false;
      }
      if (message?.type === "COLLECT_LINKEDIN_QUESTIONS") {
        sendResponse({ ok: true, questions: customQuestions() });
        return false;
      }
    } catch (error) {
      sendResponse({ ok: false, error: error.message });
      return false;
    }
    return false;
  });
})();
