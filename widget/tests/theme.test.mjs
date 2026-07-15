/**
 * Theme token resolution. Run: node --test tests/
 */
import test from "node:test";
import assert from "node:assert/strict";

import { resolveTheme } from "../src/lib/theme.ts";

test("falls back to prefers-dark when no theme", () => {
  assert.equal(resolveTheme(undefined, true).dark, true);
  assert.equal(resolveTheme(undefined, false).dark, false);
});

test("host palette.mode overrides prefers-dark", () => {
  const light = resolveTheme({ palette: { mode: "light" } }, true);
  assert.equal(light.dark, false);
});

test("reads palette colours when present", () => {
  const tokens = resolveTheme(
    {
      palette: {
        mode: "dark",
        background: { default: "#000", paper: "#111" },
        text: { primary: "#eee", secondary: "#aaa" },
        primary: { main: "#0af", contrastText: "#001" },
        error: { main: "#f00" },
      },
    },
    false,
  );
  assert.equal(tokens.dark, true);
  assert.equal(tokens.bg, "#000");
  assert.equal(tokens.panel, "#111");
  assert.equal(tokens.text, "#eee");
  assert.equal(tokens.accent, "#0af");
  assert.equal(tokens.danger, "#f00");
});

test("partial palette keeps base defaults", () => {
  const tokens = resolveTheme({ palette: { mode: "light" } }, false);
  assert.equal(typeof tokens.bg, "string");
  assert.equal(typeof tokens.accent, "string");
});
