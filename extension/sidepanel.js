const state = { preview: null, saved: null, timer: 0 };
const elements = {
  connectionDot: document.querySelector("#connection-dot"), connectionText: document.querySelector("#connection-text"),
  title: document.querySelector("#job-title"), company: document.querySelector("#job-company"),
  location: document.querySelector("#job-location"), workplace: document.querySelector("#job-workplace"), posted: document.querySelector("#job-posted"),
  capture: document.querySelector("#capture"), status: document.querySelector("#capture-status"), auto: document.querySelector("#auto-capture"),
  rematch: document.querySelector("#rematch"),
  actionStatus: document.querySelector("#action-status"),
  analysis: document.querySelector("#analysis-summary"), skills: document.querySelector("#skills"), resume: document.querySelector("#resume-link"),
  letter: document.querySelector("#letter"), letterOutput: document.querySelector("#letter-output"), start: document.querySelector("#start-review"),
  fill: document.querySelector("#fill-fields"), drafts: document.querySelector("#drafts"), draftOutput: document.querySelector("#draft-output"),
};

function setStatus(message, kind = "") { elements.status.textContent = message; elements.status.className = `status ${kind}`; }
function setActionStatus(message, kind = "") { elements.actionStatus.textContent = message; elements.actionStatus.className = `status ${kind}`; }
function activeTab() { return chrome.tabs.query({ active: true, currentWindow: true }).then(([tab]) => { if (!tab?.id) throw new Error("No active Chrome tab was found."); return tab; }); }
function isLinkedInHostname(hostname) { const value = (hostname || "").toLowerCase().replace(/\.$/, ""); return value === "linkedin.com" || value.endsWith(".linkedin.com"); }
function isLinkedInJob(tab) { try { const url = new URL(tab.url || ""); return isLinkedInHostname(url.hostname) && (url.pathname.includes("/jobs/view/") || url.searchParams.has("currentJobId")); } catch (_) { return false; } }
function isWorkdayApplication(tab) { try { return new URL(tab.url || "").hostname.endsWith(".myworkdayjobs.com"); } catch (_) { return false; } }
function isSuccessFactorsApplication(tab) { try { return new URL(tab.url || "").hostname.endsWith(".successfactors.com"); } catch (_) { return false; } }

async function sendToActive(message) {
  const tab = await activeTab();
  if (!isLinkedInJob(tab) && !isWorkdayApplication(tab) && !isSuccessFactorsApplication(tab)) throw new Error("Open a LinkedIn, Workday, or SuccessFactors application page in the active tab.");
  try { return await chrome.tabs.sendMessage(tab.id, message); }
  catch (_) { await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] }); return chrome.tabs.sendMessage(tab.id, message); }
}

async function extractPreview() {
  const response = await sendToActive({ type: "EXTRACT_LINKEDIN_JOB" });
  if (!response?.ok) throw new Error(response?.error || "The visible job could not be read.");
  state.preview = response.job;
  elements.title.textContent = response.job.title;
  elements.company.textContent = response.job.company;
  elements.location.textContent = response.job.location || "Location not shown";
  elements.workplace.textContent = response.job.workplace_type || "Workplace not shown";
  elements.posted.textContent = response.job.posting_date || "Posting date not shown";
  setStatus("Ready to capture the visible description.");
}

async function checkCompanion() {
  const response = await chrome.runtime.sendMessage({ type: "COMPANION_HEALTH" });
  const online = Boolean(response?.ok);
  elements.connectionDot.className = `dot ${online ? "online" : ""}`;
  elements.connectionText.textContent = online ? "Connected on this computer" : "Automatic companion startup needs attention";
  return online;
}

function renderAnalysis(job) {
  state.saved = job;
  const pending = job.match_score === null || job.match_score === undefined;
  elements.analysis.textContent = pending
    ? "Analysis pending. The companion is reading your newest local resume."
    : `${job.match_score}% match · ${job.recommendation || "review manually"}. ${job.match_reason || ""}`;
  elements.skills.hidden = pending;
  elements.skills.textContent = "";
  if (!pending) {
    for (const [label, value] of [["Matching", job.matching_skills], ["Missing", job.missing_skills]]) {
      const tag = document.createElement("span"); tag.textContent = `${label}: ${value || "None"}`; elements.skills.appendChild(tag);
    }
  }
  elements.resume.hidden = !job.tailored_resume_url;
  if (job.tailored_resume_url) elements.resume.href = `http://127.0.0.1:8766${job.tailored_resume_url}`;
  for (const button of [elements.letter, elements.start, elements.fill, elements.drafts]) button.disabled = pending;
}

async function loadJob(id) {
  const response = await fetch(`http://127.0.0.1:8766/api/jobs/${id}`, { cache: "no-store" });
  const body = await response.json().catch(() => ({}));
  if (!response.ok || !body.ok) throw new Error(body.error || "The saved job could not be read.");
  renderAnalysis(body.job);
  return body.job;
}

function pollAnalysis() {
  clearTimeout(state.timer);
  if (!state.saved?.id || state.saved.match_score !== null && state.saved.match_score !== undefined) return;
  state.timer = setTimeout(async () => {
    try { const job = await loadJob(state.saved.id); if (job.match_score === null || job.match_score === undefined) pollAnalysis(); }
    catch (_) { pollAnalysis(); }
  }, 1600);
}

elements.capture.addEventListener("click", async () => {
  elements.capture.disabled = true; setStatus("Saving the visible job locally…");
  try {
    if (!state.preview) await extractPreview();
    const response = await chrome.runtime.sendMessage({ type: "SAVE_LINKEDIN_JOB", job: state.preview });
    if (!response?.ok) throw new Error(response?.error || "The local companion could not save this job.");
    renderAnalysis(response.job); setStatus(`Captured job #${response.job.id}. Analysis is running.`); pollAnalysis();
  } catch (error) { setStatus(error.message, "error"); }
  finally { elements.capture.disabled = false; }
});

elements.auto.addEventListener("change", () => chrome.runtime.sendMessage({ type: "SAVE_LINKEDIN_PROFILE", profile: state.profile || {}, autoCapture: elements.auto.checked }));
elements.rematch.addEventListener("click", async () => { const r = await chrome.runtime.sendMessage({ type: "REMATCH_LINKEDIN_JOBS" }); setStatus(r?.ok ? `Queued ${r.queued} saved job(s) for matching.` : r?.error || "Matching could not be queued.", r?.ok ? "" : "error"); if (state.saved) { renderAnalysis({ ...state.saved, match_score: null }); pollAnalysis(); } });
elements.letter.addEventListener("click", async () => {
  try { const r = await chrome.runtime.sendMessage({ type: "GENERATE_LINKEDIN_COVER_LETTER", jobId: state.saved.id }); if (!r?.ok) throw new Error(r?.error || "Could not create a draft."); elements.letterOutput.textContent = r.cover_letter; elements.letterOutput.hidden = false; }
  catch (error) { setStatus(error.message, "error"); }
});
elements.start.addEventListener("click", async () => {
  if (!confirm("Continue to manual application review? You will open the application yourself; nothing will be submitted.")) return;
  await sendToActive({ type: "SHOW_ASSISTANT_STATUS", message: "Open the application yourself. When its form is visible, return here to fill only safe empty fields.", kind: "pending" });
  setStatus("Manual review started. Click Apply yourself, then use Fill safe empty fields.");
});
elements.fill.addEventListener("click", async () => {
  try { const r = await sendToActive({ type: "FILL_LINKEDIN_SAFE_FIELDS", profile: state.profile || {} }); if (!r?.ok) throw new Error(r?.error || "Safe fields could not be filled."); setStatus(r.filled?.length ? `Filled only empty fields: ${r.filled.join(", ")}. Review them.` : "No supported empty fields were found. Nothing was changed."); }
  catch (error) { setStatus(error.message, "error"); }
});
elements.drafts.addEventListener("click", async () => {
  try {
    const questions = await sendToActive({ type: "COLLECT_LINKEDIN_QUESTIONS" });
    if (!questions?.ok) throw new Error(questions?.error || "Visible questions could not be read.");
    const r = await chrome.runtime.sendMessage({ type: "GENERATE_LINKEDIN_DRAFTS", jobId: state.saved.id, questions: questions.questions });
    if (!r?.ok) throw new Error(r?.error || "Drafts could not be generated.");
    elements.draftOutput.textContent = "";
    for (const draft of r.drafts || []) { const q = document.createElement("p"); q.className = "draft-question"; q.textContent = `Question: ${draft.question}`; const a = document.createElement("p"); a.className = "draft-answer"; a.textContent = `Draft: ${draft.answer}`; elements.draftOutput.append(q, a); }
    if (!r.drafts?.length) elements.draftOutput.textContent = "No visible text-area questions were found. Review the form manually.";
    elements.draftOutput.hidden = false;
  } catch (error) { setStatus(error.message, "error"); }
});
(async () => {
  try {
    const profile = await chrome.runtime.sendMessage({ type: "GET_LINKEDIN_PROFILE" });
    if (profile?.ok) { state.profile = profile.profile; elements.auto.checked = profile.autoCapture; }
    await checkCompanion();
    const tab = await activeTab();
    if (isWorkdayApplication(tab) || isSuccessFactorsApplication(tab)) {
      const platform = isWorkdayApplication(tab) ? "Workday" : "SuccessFactors";
      elements.title.textContent = `${platform} application`;
      elements.company.textContent = "Safe autofill runs for your saved contact fields.";
      elements.location.textContent = "Only empty, supported fields";
      elements.workplace.textContent = "No declarations or uploads";
      elements.posted.textContent = "No submission actions";
      elements.capture.disabled = true;
      setStatus(`${platform} safe autofill is active. Review all values before continuing.`);
    } else {
      await extractPreview();
    }
  } catch (error) { setStatus(error.message, "error"); }
})();
