const form = document.querySelector("#profile-form");
const status = document.querySelector("#status");
const autoCapture = document.querySelector("#auto-capture");
const fields = ["first_name", "last_name", "email", "phone", "location", "linkedin_url", "website_url"];
const PROFILE_KEY = "linkedinAssistantProfile";
const AUTO_CAPTURE_KEY = "linkedinAssistantAutoCapture";

function setStatus(message, kind = "") { status.textContent = message; status.className = kind; }
async function load() {
  let profile = {};
  let enabled = true;
  try {
    const response = await chrome.runtime.sendMessage({ type: "GET_LINKEDIN_PROFILE" });
    if (!response?.ok) throw new Error(response?.error || "The profile service did not respond.");
    profile = response.profile || {};
    enabled = response.autoCapture !== false;
  } catch (_error) {
    // Profile editing should remain available even while the local companion is stopped.
    const stored = await chrome.storage.local.get([PROFILE_KEY, AUTO_CAPTURE_KEY]);
    profile = stored[PROFILE_KEY] || {};
    enabled = stored[AUTO_CAPTURE_KEY] !== false;
  }
  for (const field of fields) form.elements[field].value = profile[field] || "";
  autoCapture.checked = enabled;
  setStatus("Profile loaded locally in Chrome.");
}
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const profile = Object.fromEntries(fields.map((field) => [field, form.elements[field].value.trim()]).filter(([, value]) => value));
  try {
    await chrome.storage.local.set({ [PROFILE_KEY]: profile, [AUTO_CAPTURE_KEY]: autoCapture.checked });
    await chrome.runtime.sendMessage({ type: "BROADCAST_LINKEDIN_PROFILE_UPDATE" });
    setStatus("Saved locally in Chrome.");
  } catch (error) {
    setStatus(error.message || "The profile could not be saved.", "error");
  }
});
document.querySelector("#reload").addEventListener("click", () => load().catch((error) => setStatus(error.message, "error")));
load().catch((error) => setStatus(error.message, "error"));
