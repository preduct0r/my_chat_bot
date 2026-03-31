import test from "node:test";
import assert from "node:assert/strict";

import { shouldSubmitOnEnter } from "../web/app_logic.js";

test("Enter submits when there is text", () => {
  assert.equal(
    shouldSubmitOnEnter({
      key: "Enter",
      shiftKey: false,
      pending: false,
      hasMessage: true,
      hasFiles: false,
    }),
    true
  );
});

test("Enter submits when there are files even without text", () => {
  assert.equal(
    shouldSubmitOnEnter({
      key: "Enter",
      shiftKey: false,
      pending: false,
      hasMessage: false,
      hasFiles: true,
    }),
    true
  );
});

test("Shift+Enter does not submit", () => {
  assert.equal(
    shouldSubmitOnEnter({
      key: "Enter",
      shiftKey: true,
      pending: false,
      hasMessage: true,
      hasFiles: false,
    }),
    false
  );
});

test("Enter does not submit while pending", () => {
  assert.equal(
    shouldSubmitOnEnter({
      key: "Enter",
      shiftKey: false,
      pending: true,
      hasMessage: true,
      hasFiles: false,
    }),
    false
  );
});

test("Enter does not submit when composer is empty", () => {
  assert.equal(
    shouldSubmitOnEnter({
      key: "Enter",
      shiftKey: false,
      pending: false,
      hasMessage: false,
      hasFiles: false,
    }),
    false
  );
});
