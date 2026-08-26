"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const projectRoot = path.resolve(__dirname, "..");

test("side panel element bindings match its HTML", () => {
  const script = fs.readFileSync(path.join(projectRoot, "extension", "sidepanel.js"), "utf8");
  const document = fs.readFileSync(path.join(projectRoot, "extension", "sidepanel.html"), "utf8");
  const declarations = [...script.matchAll(/(\w+):\s*document\.querySelector\("#([^"\s]+)"\)/g)];
  const declaredNames = new Set(declarations.map((match) => match[1]));
  const referencedNames = new Set([...script.matchAll(/elements\.(\w+)/g)].map((match) => match[1]));
  const htmlIds = new Set([...document.matchAll(/\sid="([^"]+)"/g)].map((match) => match[1]));

  assert.deepEqual([...referencedNames].filter((name) => !declaredNames.has(name)), []);
  assert.deepEqual(declarations.filter((match) => !htmlIds.has(match[2])).map((match) => match[2]), []);
});

test("LinkedIn checks reject suffix lookalike domains", () => {
  for (const relativePath of ["extension/content.js", "extension/service-worker.js", "extension/sidepanel.js"]) {
    const script = fs.readFileSync(path.join(projectRoot, relativePath), "utf8");
    assert.doesNotMatch(script, /hostname\.endsWith\(["']linkedin\.com["']\)/);
    assert.match(script, /\.endsWith\(["']\.linkedin\.com["']\)/);
  }
});
