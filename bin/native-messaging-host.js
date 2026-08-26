#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const { spawn } = require("node:child_process");

const PACKAGE_ROOT = path.resolve(__dirname, "..");
const HEALTH_URL = "http://127.0.0.1:8766/api/health";
const MAX_MESSAGE_BYTES = 1024 * 1024;

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

function pythonExecutable() {
  if (process.platform === "win32") {
    const windowless = path.join(runtimeRoot(), ".venv", "Scripts", "pythonw.exe");
    return fs.existsSync(windowless) ? windowless : path.join(runtimeRoot(), ".venv", "Scripts", "python.exe");
  }
  return path.join(runtimeRoot(), ".venv", "bin", "python");
}

function isHealthy(timeout = 700) {
  return new Promise((resolve) => {
    const request = http.get(HEALTH_URL, { timeout }, (response) => {
      response.resume();
      resolve(response.statusCode === 200);
    });
    request.on("timeout", () => { request.destroy(); resolve(false); });
    request.on("error", () => resolve(false));
  });
}

async function waitForHealth() {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    if (await isHealthy()) return true;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  return false;
}

async function startCompanion(message) {
  if (!message || message.action !== "start") {
    return { ok: false, error: "The native helper accepts only the start action." };
  }
  if (await isHealthy()) return { ok: true, alreadyRunning: true };

  const python = pythonExecutable();
  if (!fs.existsSync(python)) {
    return { ok: false, error: "The local Python environment is missing. Run the project setup command again." };
  }
  const child = spawn(python, ["-m", "companion.server"], {
    cwd: PACKAGE_ROOT,
    env: { ...process.env, JOB_ASSISTANT_HOME: runtimeRoot(), PYTHONUNBUFFERED: "1" },
    detached: true,
    windowsHide: true,
    stdio: "ignore",
  });
  child.once("error", (error) => process.stderr.write(`Could not start companion: ${error.message}\n`));
  child.unref();
  if (!(await waitForHealth())) {
    return { ok: false, error: "Chrome started the helper, but the local companion did not become ready." };
  }
  return { ok: true, started: true, pid: child.pid };
}

function sendMessage(message) {
  const payload = Buffer.from(JSON.stringify(message), "utf8");
  const header = Buffer.alloc(4);
  header.writeUInt32LE(payload.length, 0);
  process.stdout.write(Buffer.concat([header, payload]), () => process.exit(message.ok ? 0 : 1));
}

let input = Buffer.alloc(0);
let handled = false;

process.stdin.on("data", (chunk) => {
  if (handled) return;
  input = Buffer.concat([input, chunk]);
  if (input.length < 4) return;
  const length = input.readUInt32LE(0);
  if (length < 2 || length > MAX_MESSAGE_BYTES) {
    handled = true;
    sendMessage({ ok: false, error: "Chrome sent an invalid native message." });
    return;
  }
  if (input.length < 4 + length) return;
  handled = true;
  process.stdin.pause();
  try {
    const message = JSON.parse(input.subarray(4, 4 + length).toString("utf8"));
    startCompanion(message).then(sendMessage).catch((error) => sendMessage({ ok: false, error: error.message }));
  } catch (_error) {
    sendMessage({ ok: false, error: "Chrome sent malformed JSON to the native helper." });
  }
});

process.stdin.on("error", (error) => {
  process.stderr.write(`Native message input failed: ${error.message}\n`);
  process.exit(1);
});
