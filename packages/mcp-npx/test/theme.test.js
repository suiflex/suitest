"use strict";

const { test } = require("node:test");
const assert = require("node:assert");
const { PassThrough } = require("node:stream");

const theme = require("../lib/theme.js");

function ttyStream() {
  const s = new PassThrough();
  s.isTTY = true;
  return s;
}

function nonTtyStream() {
  const s = new PassThrough();
  s.isTTY = false;
  return s;
}

test("colorEnabled is false on a non-TTY stream", () => {
  assert.strictEqual(theme.colorEnabled(nonTtyStream()), false);
});

test("colorEnabled is false when NO_COLOR is set, even on a TTY", () => {
  const prev = process.env.NO_COLOR;
  process.env.NO_COLOR = "1";
  try {
    assert.strictEqual(theme.colorEnabled(ttyStream()), false);
  } finally {
    if (prev === undefined) delete process.env.NO_COLOR;
    else process.env.NO_COLOR = prev;
  }
});

test("colorEnabled is true on a TTY without NO_COLOR", () => {
  const prev = process.env.NO_COLOR;
  delete process.env.NO_COLOR;
  try {
    assert.strictEqual(theme.colorEnabled(ttyStream()), true);
  } finally {
    if (prev !== undefined) process.env.NO_COLOR = prev;
  }
});

test("color wrappers return the raw string unchanged when color disabled", () => {
  const out = nonTtyStream();
  assert.strictEqual(theme.accent("hello", out), "hello");
  assert.strictEqual(theme.red("hello", out), "hello");
});

test("color wrappers add ANSI codes when color enabled", () => {
  const prev = process.env.NO_COLOR;
  delete process.env.NO_COLOR;
  try {
    const out = ttyStream();
    const painted = theme.accent("hello", out);
    assert.notStrictEqual(painted, "hello");
    assert.ok(painted.includes("hello"));
  } finally {
    if (prev !== undefined) process.env.NO_COLOR = prev;
  }
});

test("panel() produces lines of consistent width", () => {
  const out = nonTtyStream();
  const rendered = theme.panel(["short", "a much longer line here"], {}, out);
  const lines = rendered.split("\n");
  const widths = new Set(lines.map((l) => l.length));
  assert.strictEqual(widths.size, 1, `expected uniform width, got: ${[...widths]}`);
});

test("banner() collapses to plain text when color disabled", () => {
  const out = nonTtyStream();
  const rendered = theme.banner(out);
  assert.ok(!rendered.includes("\x1b["));
  assert.ok(rendered.includes("S U I T E S T"));
});

test("banner() uses the accent color, not the neutral border color", () => {
  const prev = process.env.NO_COLOR;
  delete process.env.NO_COLOR;
  try {
    const out = ttyStream();
    const rendered = theme.banner(out);
    const accentCode = theme.accent("Z", out).split("Z")[0];
    const borderCode = theme.border("Z", out).split("Z")[0];
    assert.ok(rendered.includes(accentCode), "banner should carry the accent ANSI code");
    assert.ok(!rendered.includes(borderCode), "banner should not carry the neutral border code");
  } finally {
    if (prev !== undefined) process.env.NO_COLOR = prev;
  }
});

test("gutter() prefixes a line with the connector column", () => {
  const out = nonTtyStream();
  assert.strictEqual(theme.gutter("hello", {}, out), "│ hello");
  assert.strictEqual(theme.gutter("", {}, out), "│");
});

test("point() puts the marker at column 0, no leading gutter pipe", () => {
  const out = nonTtyStream();
  assert.strictEqual(theme.point("hello"), "◇ hello");
  assert.strictEqual(theme.point("hello", { marker: "◆" }), "◆ hello");
  assert.ok(!theme.point("hello", {}, out).startsWith("│"));
});

test("step() wraps every body line with the gutter and brackets with blank connectors", () => {
  const out = nonTtyStream();
  const rendered = theme.step("do the thing", ["line one", "line two"], {}, out);
  const lines = rendered.split("\n");
  assert.ok(lines[0].startsWith("◇ do the thing"));
  assert.strictEqual(lines[1], "│");
  assert.ok(lines[2].includes("line one"));
  assert.ok(lines[2].startsWith("│"));
  assert.ok(lines[3].includes("line two"));
  assert.strictEqual(lines[4], "│");
});
