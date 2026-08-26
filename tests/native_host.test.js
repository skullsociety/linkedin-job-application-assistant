"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const crypto = require("node:crypto");
const path = require("node:path");
const test = require("node:test");
const { spawnSync } = require("node:child_process");

const projectRoot = path.resolve(__dirname, "..");

test("manifest declares a stable native-messaging extension identity", () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(projectRoot, "extension", "manifest.json"), "utf8"));
  const packageMetadata = JSON.parse(fs.readFileSync(path.join(projectRoot, "package.json"), "utf8"));
  assert.equal(manifest.version, packageMetadata.version);
  assert.ok(manifest.permissions.includes("nativeMessaging"));
  assert.match(manifest.key, /^[A-Za-z0-9+/=]+$/);
  const key = Buffer.from(manifest.key, "base64");
  const expectedId = crypto.createHash("sha256").update(key).digest().subarray(0, 16).toString("hex")
    .replace(/[0-9a-f]/g, (character) => String.fromCharCode(97 + Number.parseInt(character, 16)));
  const companion = fs.readFileSync(path.join(projectRoot, "companion", "server.py"), "utf8");
  const cli = spawnSync(process.execPath, [path.join(projectRoot, "bin", "linkedin-job-assistant.js"), "chrome-extension-id"], { encoding: "utf8" });
  assert.equal(cli.status, 0);
  assert.equal(cli.stdout.trim(), expectedId);
  assert.match(fs.readFileSync(path.join(projectRoot, "extension", "service-worker.js"), "utf8"), /com\.linkedin_job_assistant\.launcher/);
  assert.match(companion, new RegExp(`CHROME_EXTENSION_ORIGIN = "chrome-extension://${expectedId}"`));
});

test("native helper rejects actions other than start using Chrome framing", () => {
  const request = Buffer.from(JSON.stringify({ action: "delete" }), "utf8");
  const header = Buffer.alloc(4);
  header.writeUInt32LE(request.length, 0);
  const result = spawnSync(process.execPath, [path.join(projectRoot, "bin", "native-messaging-host.js")], {
    input: Buffer.concat([header, request]),
    encoding: null,
    timeout: 5000,
  });
  assert.equal(result.status, 1);
  assert.ok(result.stdout.length >= 4);
  const responseLength = result.stdout.readUInt32LE(0);
  const response = JSON.parse(result.stdout.subarray(4, 4 + responseLength).toString("utf8"));
  assert.equal(response.ok, false);
  assert.match(response.error, /only the start action/i);
});
