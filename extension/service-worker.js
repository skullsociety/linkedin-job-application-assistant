const COMPANION_BASE = "http://127.0.0.1:8766";
const NATIVE_HOST_NAME = "com.linkedin_job_assistant.launcher";
const PROFILE_KEY = "linkedinAssistantProfile";
const AUTO_CAPTURE_KEY = "linkedinAssistantAutoCapture";
let nativeStartPromise = null;

async function rawRequest(path, options = {}, timeoutMs = 8000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${COMPANION_BASE}${path}`, { cache: "no-store", ...options, signal: controller.signal });
    const body = await response.json().catch(() => ({}));
    if (!response.ok || !body.ok) throw new Error(body.error || `Local companion request failed (${response.status}).`);
    return body;
  } finally {
    clearTimeout(timeout);
  }
}

function isConnectionError(error) {
  return error?.name === "AbortError" || error instanceof TypeError;
}

function requestNativeStart() {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendNativeMessage(NATIVE_HOST_NAME, { action: "start" }, (response) => {
      const nativeError = chrome.runtime.lastError;
      if (nativeError) {
        reject(new Error(`${nativeError.message} Run the one-time Chrome integration setup again.`));
        return;
      }
      if (!response?.ok) {
        reject(new Error(response?.error || "The registered Chrome helper could not start the companion."));
        return;
      }
      resolve(response);
    });
  });
}

async function ensureCompanionRunning() {
  try {
    await rawRequest("/api/health", {}, 700);
    return;
  } catch (error) {
    if (!isConnectionError(error)) throw error;
  }
  if (!nativeStartPromise) {
    nativeStartPromise = requestNativeStart().finally(() => { nativeStartPromise = null; });
  }
  await nativeStartPromise;
  for (let attempt = 0; attempt < 20; attempt += 1) {
    try {
      await rawRequest("/api/health", {}, 700);
      return;
    } catch (error) {
      if (!isConnectionError(error)) throw error;
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
  }
  throw new Error("Chrome launched the local helper, but the companion did not become ready.");
}

async function request(path, options = {}) {
  try {
    return await rawRequest(path, options);
  } catch (error) {
    if (!isConnectionError(error)) throw error;
  }
  try {
    await ensureCompanionRunning();
  } catch (startError) {
    throw new Error(`Cannot start the local companion automatically. ${startError.message}`);
  }
  return rawRequest(path, options);
}

async function ensureProfile() {
  const stored = await chrome.storage.local.get([PROFILE_KEY, AUTO_CAPTURE_KEY]);
  if (!stored[PROFILE_KEY]) {
    let profile = {};
    try {
      const response = await request("/api/profile");
      profile = response.profile || {};
    } catch (_error) {
      // The profile page still opens with empty fields when the companion is not running.
    }
    await chrome.storage.local.set({
      [PROFILE_KEY]: profile,
      [AUTO_CAPTURE_KEY]: stored[AUTO_CAPTURE_KEY] ?? true,
    });
  }
  return (await chrome.storage.local.get([PROFILE_KEY, AUTO_CAPTURE_KEY]));
}

async function restrictProfileStorage() {
  // Contact details stay accessible to extension pages and the service worker,
  // rather than being exposed directly to every page where a content script runs.
  await chrome.storage.local.setAccessLevel({ accessLevel: "TRUSTED_CONTEXTS" });
}

async function broadcastProfileUpdate() {
  const data = await ensureProfile();
  const tabs = await chrome.tabs.query({ url: ["https://www.linkedin.com/*", "https://linkedin.com/*", "https://*.myworkdayjobs.com/*", "https://*.successfactors.com/*"] });
  await Promise.all(tabs.filter((tab) => tab.id).map((tab) => chrome.tabs.sendMessage(tab.id, {
    type: "LINKEDIN_PROFILE_UPDATED",
    profile: data[PROFILE_KEY] || {},
    autoCapture: data[AUTO_CAPTURE_KEY] !== false,
  }).catch(() => {})));
}

async function showStatus(tabId, message, kind = "pending") {
  if (!tabId) return;
  try {
    await chrome.tabs.sendMessage(tabId, { type: "SHOW_ASSISTANT_STATUS", message, kind });
  } catch (_error) {
    // A tab can change while a capture is being saved; its local record still exists.
  }
}

async function saveJob(job) {
  return request("/api/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(job),
  });
}

async function captureCurrentJob(tab) {
  if (!tab?.id || !isLinkedInJob(tab.url)) throw new Error("Open a fully loaded LinkedIn job-detail page first.");
  let extraction;
  try {
    extraction = await chrome.tabs.sendMessage(tab.id, { type: "EXTRACT_LINKEDIN_JOB" });
  } catch (_error) {
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] });
    extraction = await chrome.tabs.sendMessage(tab.id, { type: "EXTRACT_LINKEDIN_JOB" });
  }
  if (!extraction?.ok) throw new Error(extraction?.error || "The visible job could not be extracted.");
  await showStatus(tab.id, "Saving the visible job locally…");
  const saved = await saveJob(extraction.job);
  await showStatus(tab.id, `Captured job #${saved.job.id}. Resume analysis is running.`, "success");
  await chrome.action.setBadgeText({ text: "OK", tabId: tab.id });
  await chrome.action.setBadgeBackgroundColor({ color: "#057642", tabId: tab.id });
  return saved;
}

function isLinkedInJob(url) {
  try {
    const parsed = new URL(url || "");
    const hostname = parsed.hostname.toLowerCase().replace(/\.$/, "");
    const isLinkedIn = hostname === "linkedin.com" || hostname.endsWith(".linkedin.com");
    return isLinkedIn && (parsed.pathname.includes("/jobs/view/") || parsed.searchParams.has("currentJobId"));
  } catch (_error) {
    return false;
  }
}

async function openDashboard() {
  await request("/api/health");
  const target = `${COMPANION_BASE}/`;
  const existing = await chrome.tabs.query({ url: `${COMPANION_BASE}/*` });
  if (existing[0]?.id) {
    await chrome.tabs.update(existing[0].id, { active: true });
    await chrome.windows.update(existing[0].windowId, { focused: true });
    return;
  }
  await chrome.tabs.create({ url: target });
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
  restrictProfileStorage().catch(() => {}).then(ensureCompanionRunning).then(ensureProfile).catch(() => {});
});

chrome.runtime.onStartup.addListener(() => restrictProfileStorage().catch(() => {}).then(ensureCompanionRunning).then(ensureProfile).catch(() => {}));

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === "AUTO_CAPTURE_LINKEDIN_JOB") {
    captureCurrentJob(sender.tab)
      .then((saved) => sendResponse({ ok: true, saved }))
      .catch(async (error) => {
        await showStatus(sender.tab?.id, error.message, "error");
        sendResponse({ ok: false, error: error.message });
      });
    return true;
  }
  if (message?.type === "SAVE_LINKEDIN_JOB") {
    saveJob(message.job).then(sendResponse).catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }
  if (message?.type === "COMPANION_HEALTH") {
    request("/api/health").then((body) => sendResponse({ ok: true, body })).catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }
  if (message?.type === "GET_LINKEDIN_PROFILE") {
    ensureProfile().then((data) => sendResponse({ ok: true, profile: data[PROFILE_KEY] || {}, autoCapture: data[AUTO_CAPTURE_KEY] !== false })).catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }
  if (message?.type === "SAVE_LINKEDIN_PROFILE") {
    chrome.storage.local.set({ [PROFILE_KEY]: message.profile || {}, [AUTO_CAPTURE_KEY]: message.autoCapture !== false })
      .then(broadcastProfileUpdate)
      .then(() => sendResponse({ ok: true }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }
  if (message?.type === "BROADCAST_LINKEDIN_PROFILE_UPDATE") {
    broadcastProfileUpdate().then(() => sendResponse({ ok: true })).catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }
  if (message?.type === "GENERATE_LINKEDIN_DRAFTS") {
    request(`/api/jobs/${message.jobId}/drafts`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ questions: message.questions || [] }) })
      .then(sendResponse).catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }
  if (message?.type === "GENERATE_LINKEDIN_COVER_LETTER") {
    request(`/api/jobs/${message.jobId}/cover-letter`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })
      .then(sendResponse).catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }
  if (message?.type === "REMATCH_LINKEDIN_JOBS") {
    request("/api/jobs/rematch", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })
      .then(sendResponse).catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }
  if (message?.type === "OPEN_LINKEDIN_DASHBOARD") {
    openDashboard().then(() => sendResponse({ ok: true })).catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }
  return false;
});

chrome.commands.onCommand.addListener(async (command, tab) => {
  try {
    if (command === "capture-current-job") await captureCurrentJob(tab);
    if (command === "open-local-dashboard") await openDashboard();
  } catch (error) {
    await showStatus(tab?.id, error.message, "error");
  }
});
