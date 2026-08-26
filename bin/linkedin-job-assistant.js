#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const crypto = require("node:crypto");
const { spawn, spawnSync } = require("node:child_process");

const PACKAGE_ROOT = path.resolve(__dirname, "..");
const DASHBOARD_URL = "http://127.0.0.1:8766/";
const TASK_NAME = "LinkedIn Job Application Assistant";
const NATIVE_HOST_NAME = "com.linkedin_job_assistant.launcher";
const NATIVE_REGISTRY_KEY = `HKCU\\Software\\Google\\Chrome\\NativeMessagingHosts\\${NATIVE_HOST_NAME}`;

function isPackagedInstall() {
  return PACKAGE_ROOT.split(path.sep).includes("node_modules");
}

function defaultRuntimeRoot() {
  if (!isPackagedInstall()) return PACKAGE_ROOT;
  if (process.platform === "win32") {
    return path.join(process.env.LOCALAPPDATA || process.env.APPDATA || os.homedir(), "LinkedInJobAssistant");
  }
  if (process.platform === "darwin") return path.join(os.homedir(), "Library", "Application Support", "LinkedInJobAssistant");
  return path.join(process.env.XDG_DATA_HOME || path.join(os.homedir(), ".local", "share"), "linkedin-job-assistant");
}

function runtimeRoot() {
  return path.resolve(process.env.JOB_ASSISTANT_HOME || defaultRuntimeRoot());
}

function runtimeEnvironment() {
  return { ...process.env, JOB_ASSISTANT_HOME: runtimeRoot(), PYTHONUNBUFFERED: "1" };
}

function venvPython({ windowless = false } = {}) {
  if (process.platform === "win32") {
    return path.join(runtimeRoot(), ".venv", "Scripts", windowless ? "pythonw.exe" : "python.exe");
  }
  return path.join(runtimeRoot(), ".venv", "bin", "python");
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, { cwd: PACKAGE_ROOT, encoding: "utf8", stdio: "inherit", ...options });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${path.basename(command)} exited with code ${result.status}.`);
}

function pythonCandidates() {
  const defaults = process.platform === "win32"
    ? [{ command: "py", prefix: ["-3"] }, { command: "python", prefix: [] }, { command: "python3", prefix: [] }]
    : [{ command: "python3", prefix: [] }, { command: "python", prefix: [] }];
  if (process.platform === "win32" && process.env.LOCALAPPDATA) {
    const localAppData = process.env.LOCALAPPDATA;
    const directInstall = path.join(localAppData, "Python", "bin", "python.exe");
    if (fs.existsSync(directInstall)) defaults.push({ command: directInstall, prefix: [] });

    const standardRoot = path.join(localAppData, "Programs", "Python");
    if (fs.existsSync(standardRoot)) {
      const installations = fs.readdirSync(standardRoot, { withFileTypes: true })
        .filter((entry) => entry.isDirectory() && /^Python\d+$/i.test(entry.name))
        .sort((left, right) => right.name.localeCompare(left.name, undefined, { numeric: true }));
      for (const installation of installations) {
        const executable = path.join(standardRoot, installation.name, "python.exe");
        if (fs.existsSync(executable)) defaults.push({ command: executable, prefix: [] });
      }
    }
  }
  const configured = String(process.env.JOB_ASSISTANT_PYTHON || "").trim();
  return configured ? [{ command: configured, prefix: [] }, ...defaults] : defaults;
}

function findSystemPython() {
  for (const candidate of pythonCandidates()) {
    const probe = spawnSync(candidate.command, [...candidate.prefix, "-c", "import sys; print(sys.version_info[:2])"], {
      encoding: "utf8",
      windowsHide: true,
    });
    if (probe.status === 0 && /\(3,\s*(?:1[1-9]|[2-9]\d)\)/.test(probe.stdout || "")) return candidate;
  }
  throw new Error("Python 3.11 or newer was not found. Install Python or set JOB_ASSISTANT_PYTHON to its executable, then run setup again.");
}

function ensureRuntimeFolders() {
  for (const name of ["data", "exports", "logs", "resumes"]) {
    fs.mkdirSync(path.join(runtimeRoot(), name), { recursive: true });
  }
  const config = path.join(runtimeRoot(), "config.toml");
  if (!fs.existsSync(config)) fs.copyFileSync(path.join(PACKAGE_ROOT, "config.example.toml"), config);
}

function extensionLocation() {
  return isPackagedInstall() ? path.join(runtimeRoot(), "extension") : path.join(PACKAGE_ROOT, "extension");
}

function copyExtensionForPackagedInstall() {
  const destination = extensionLocation();
  if (!isPackagedInstall()) return destination;
  fs.mkdirSync(destination, { recursive: true });
  fs.cpSync(path.join(PACKAGE_ROOT, "extension"), destination, { recursive: true, force: true });
  return destination;
}

function extensionIdentity() {
  const manifest = JSON.parse(fs.readFileSync(path.join(PACKAGE_ROOT, "extension", "manifest.json"), "utf8"));
  if (typeof manifest.key !== "string" || !/^[A-Za-z0-9+/=]+$/.test(manifest.key)) {
    throw new Error("The Chrome extension does not have a valid stable public key.");
  }
  const publicKey = Buffer.from(manifest.key, "base64");
  if (publicKey.length < 64) throw new Error("The Chrome extension public key is incomplete.");
  return crypto.createHash("sha256").update(publicKey).digest().subarray(0, 16).toString("hex")
    .replace(/[0-9a-f]/g, (character) => String.fromCharCode(97 + Number.parseInt(character, 16)));
}

function nativeHostFolder() {
  return path.join(runtimeRoot(), "native-messaging");
}

function nativeManifestPath() {
  if (process.platform === "win32") return path.join(nativeHostFolder(), `${NATIVE_HOST_NAME}.json`);
  if (process.platform === "darwin") {
    return path.join(os.homedir(), "Library", "Application Support", "Google", "Chrome", "NativeMessagingHosts", `${NATIVE_HOST_NAME}.json`);
  }
  return path.join(os.homedir(), ".config", "google-chrome", "NativeMessagingHosts", `${NATIVE_HOST_NAME}.json`);
}

function safeBatchValue(value) {
  const text = String(value);
  if (text.includes(String.fromCharCode(13)) || text.includes(String.fromCharCode(10)) || text.includes('"')) {
    throw new Error("A generated native-host path contains unsupported characters.");
  }
  return text.replace(/%/g, "%%");
}

function shellQuoted(value) {
  return `'${String(value).replace(/'/g, `'"'"'`)}'`;
}

function writeNativeHostFiles() {
  const folder = nativeHostFolder();
  fs.mkdirSync(folder, { recursive: true });
  const nativeScript = path.join(PACKAGE_ROOT, "bin", "native-messaging-host.js");
  let launcher;
  if (process.platform === "win32") {
    launcher = path.join(folder, "launch-native-host.bat");
    const contents = [
      "@echo off",
      "setlocal DisableDelayedExpansion",
      `set "JOB_ASSISTANT_HOME=${safeBatchValue(runtimeRoot())}"`,
      `"${safeBatchValue(process.execPath)}" "${safeBatchValue(nativeScript)}" %*`,
      "",
    ].join("\r\n");
    fs.writeFileSync(launcher, contents, "utf8");
  } else {
    launcher = path.join(folder, "launch-native-host.sh");
    const contents = [
      "#!/bin/sh",
      `export JOB_ASSISTANT_HOME=${shellQuoted(runtimeRoot())}`,
      `exec ${shellQuoted(process.execPath)} ${shellQuoted(nativeScript)} "$@"`,
      "",
    ].join("\n");
    fs.writeFileSync(launcher, contents, { encoding: "utf8", mode: 0o755 });
    fs.chmodSync(launcher, 0o755);
  }

  const manifestPath = nativeManifestPath();
  fs.mkdirSync(path.dirname(manifestPath), { recursive: true });
  const manifest = {
    name: NATIVE_HOST_NAME,
    description: "Starts the local LinkedIn Job Application Assistant companion when Chrome requests it.",
    path: launcher,
    type: "stdio",
    allowed_origins: [`chrome-extension://${extensionIdentity()}/`],
  };
  fs.writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  return { launcher, manifestPath };
}

function chromeHostIsRegistered() {
  const filesExist = fs.existsSync(nativeManifestPath()) && fs.existsSync(path.join(
    nativeHostFolder(), process.platform === "win32" ? "launch-native-host.bat" : "launch-native-host.sh",
  ));
  if (!filesExist) return false;
  if (process.platform !== "win32") return true;
  const result = spawnSync("reg.exe", ["QUERY", NATIVE_REGISTRY_KEY, "/ve"], { encoding: "utf8", windowsHide: true });
  return result.status === 0;
}

function installChromeHost() {
  ensureSetup();
  const files = writeNativeHostFiles();
  if (process.platform === "win32") {
    run("reg.exe", ["ADD", NATIVE_REGISTRY_KEY, "/ve", "/t", "REG_SZ", "/d", files.manifestPath, "/f"]);
  }
  console.log("Chrome-triggered companion startup installed for the current user.");
  console.log(`Extension ID: ${extensionIdentity()}`);
  console.log(`Native host manifest: ${files.manifestPath}`);
  console.log(`Chrome extension folder: ${copyExtensionForPackagedInstall()}`);
  console.log("Reload the extension from chrome://extensions. The companion will then start automatically with Chrome.");
}

function removeChromeHost() {
  if (process.platform === "win32") {
    const existing = spawnSync("reg.exe", ["QUERY", NATIVE_REGISTRY_KEY], { encoding: "utf8", windowsHide: true });
    if (existing.status === 0) run("reg.exe", ["DELETE", NATIVE_REGISTRY_KEY, "/f"]);
  }
  const files = [
    nativeManifestPath(),
    path.join(nativeHostFolder(), process.platform === "win32" ? "launch-native-host.bat" : "launch-native-host.sh"),
  ];
  for (const file of files) {
    if (fs.existsSync(file) && fs.statSync(file).isFile()) fs.unlinkSync(file);
  }
  console.log("Chrome-triggered companion startup removed. User data was not deleted.");
}

function setup() {
  console.log(`Application files: ${PACKAGE_ROOT}`);
  console.log(`Private user data: ${runtimeRoot()}`);
  ensureRuntimeFolders();
  copyExtensionForPackagedInstall();
  const python = venvPython();
  if (!fs.existsSync(python)) {
    const systemPython = findSystemPython();
    console.log("Creating the private Python environment…");
    run(systemPython.command, [...systemPython.prefix, "-m", "venv", path.join(runtimeRoot(), ".venv")]);
  }
  console.log("Installing the declared Python packages…");
  run(python, ["-m", "pip", "install", "-r", path.join(PACKAGE_ROOT, "requirements.txt")], { env: runtimeEnvironment() });
  console.log("\nSetup complete.");
  console.log(`Chrome extension folder: ${copyExtensionForPackagedInstall()}`);
  console.log("Next, run the Chrome integration install command and load this folder from chrome://extensions.");
}

function ensureSetup() {
  ensureRuntimeFolders();
  copyExtensionForPackagedInstall();
  if (!fs.existsSync(venvPython())) {
    console.log("First run: preparing the local Python environment.");
    setup();
  }
}

function isHealthy(timeout = 700) {
  return new Promise((resolve) => {
    const request = http.get(`${DASHBOARD_URL}api/health`, { timeout }, (response) => {
      response.resume();
      resolve(response.statusCode === 200);
    });
    request.on("timeout", () => { request.destroy(); resolve(false); });
    request.on("error", () => resolve(false));
  });
}

async function waitForHealth() {
  for (let attempt = 0; attempt < 30; attempt += 1) {
    if (await isHealthy()) return true;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  return false;
}

async function start({ background = false } = {}) {
  ensureSetup();
  if (await isHealthy()) {
    console.log(`The companion is already running at ${DASHBOARD_URL}`);
    return;
  }
  const executable = background && fs.existsSync(venvPython({ windowless: true }))
    ? venvPython({ windowless: true })
    : venvPython();
  const child = spawn(executable, ["-m", "companion.server"], {
    cwd: PACKAGE_ROOT,
    env: runtimeEnvironment(),
    detached: background,
    windowsHide: background,
    stdio: background ? "ignore" : "inherit",
  });
  if (!background) {
    child.on("error", (error) => { console.error(error.message); process.exitCode = 1; });
    return;
  }
  child.unref();
  if (!(await waitForHealth())) throw new Error("The companion did not become ready. Run the start command without --background to see the error.");
  console.log(`The companion started in the background at ${DASHBOARD_URL}`);
}

function openBrowser(url) {
  const commands = process.platform === "win32"
    ? ["cmd.exe", ["/d", "/s", "/c", "start", "", url]]
    : process.platform === "darwin" ? ["open", [url]] : ["xdg-open", [url]];
  const child = spawn(commands[0], commands[1], { detached: true, stdio: "ignore", windowsHide: true });
  child.unref();
}

async function dashboard() {
  await start({ background: true });
  openBrowser(DASHBOARD_URL);
}

function extensionPath() {
  ensureRuntimeFolders();
  console.log(copyExtensionForPackagedInstall());
}

async function doctor() {
  const checks = [
    ["Application files", PACKAGE_ROOT],
    ["Private user data", runtimeRoot()],
    ["Python environment", fs.existsSync(venvPython()) ? venvPython() : "Not installed — run setup"],
    ["Chrome extension", fs.existsSync(extensionLocation()) ? extensionLocation() : "Not prepared — run setup"],
    ["Chrome-triggered startup", chromeHostIsRegistered() ? "Installed" : "Not installed — run the Chrome integration install command"],
    ["Local companion", (await isHealthy()) ? `Running at ${DASHBOARD_URL}` : "Not running"],
  ];
  for (const [label, value] of checks) console.log(`${label}: ${value}`);
}

function vbsQuoted(value) {
  return String(value).replace(/"/g, '""');
}

function writeAutostartLauncher() {
  const launcher = path.join(runtimeRoot(), "start-companion-hidden.vbs");
  const command = `"${process.execPath}" "${__filename}" start --background`;
  const script = [
    'Set shell = CreateObject("WScript.Shell")',
    `shell.Run "${vbsQuoted(command)}", 0, False`,
    "",
  ].join("\r\n");
  fs.writeFileSync(launcher, script, "utf8");
  return launcher;
}

function installAutostart() {
  if (process.platform !== "win32") throw new Error("Automatic-start registration is currently supported on Windows only.");
  ensureSetup();
  const launcher = writeAutostartLauncher();
  const wscript = path.join(process.env.WINDIR || "C:\\Windows", "System32", "wscript.exe");
  run("schtasks.exe", ["/Create", "/TN", TASK_NAME, "/SC", "ONLOGON", "/TR", `"${wscript}" "${launcher}"`, "/F"]);
  console.log("Automatic startup installed for the current Windows account.");
}

function removeAutostart() {
  if (process.platform !== "win32") throw new Error("Automatic-start registration is currently supported on Windows only.");
  run("schtasks.exe", ["/Delete", "/TN", TASK_NAME, "/F"]);
  console.log("Automatic startup removed. User data was not deleted.");
}

function usage() {
  console.log(`Usage: linkedin-job-assistant <command>

Commands:
  setup               Prepare Python and private user folders
  start [--background] Start the local companion
  dashboard           Start the companion and open the local dashboard
  doctor              Show installation and health information
  extension-path      Print the folder to load in chrome://extensions
  chrome-extension-id Print the extension ID used by the native host
  install-chrome-host Start the companion automatically when Chrome starts
  remove-chrome-host  Remove Chrome-triggered startup without deleting data
  install-autostart   Start the companion automatically at Windows login
  remove-autostart    Remove automatic startup without deleting user data`);
}

async function main() {
  const [command = "help", ...args] = process.argv.slice(2);
  if (command === "setup") setup();
  else if (command === "start") await start({ background: args.includes("--background") });
  else if (command === "dashboard") await dashboard();
  else if (command === "doctor") await doctor();
  else if (command === "extension-path") extensionPath();
  else if (command === "chrome-extension-id") console.log(extensionIdentity());
  else if (command === "install-chrome-host") installChromeHost();
  else if (command === "remove-chrome-host") removeChromeHost();
  else if (command === "install-autostart") installAutostart();
  else if (command === "remove-autostart") removeAutostart();
  else if (["help", "--help", "-h"].includes(command)) usage();
  else throw new Error(`Unknown command: ${command}`);
}

main().catch((error) => {
  console.error(`Error: ${error.message}`);
  process.exitCode = 1;
});


