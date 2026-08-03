import test from "node:test";
import assert from "node:assert/strict";

import {
  DEFAULT_PROFILE,
  describeProfile,
  loadProfile,
  normalizeAxis,
  saveProfile,
  toInternalAxis,
} from "../src/lib/persona-profile.js";

test("normalizes display axes and converts to internal values", () => {
  assert.equal(normalizeAxis(140), 100);
  assert.equal(normalizeAxis(-140), -100);
  assert.equal(normalizeAxis("45.4"), 45);
  assert.equal(toInternalAxis(45), 0.45);
});

test("describes strong positive affinity consistently", () => {
  assert.match(
    describeProfile({ x: 75, y: 0, z: 0, mbti: "INFJ" }),
    /温暖|主动关心/,
  );
});

test("describes negative rationality and expressive values", () => {
  const description = describeProfile({
    x: 0,
    y: -65,
    z: -40,
    mbti: "ISFP",
  });

  assert.match(description, /感受|直觉/);
  assert.match(description, /克制|平静/);
});

test("falls back when storage contains invalid JSON", () => {
  assert.deepEqual(loadProfile({ getItem: () => "{" }), DEFAULT_PROFILE);
});

test("saves validated profile values and restores them", () => {
  let stored = "";
  const storage = {
    getItem: () => stored,
    setItem: (_key, value) => { stored = value; },
  };

  const saved = saveProfile(storage, {
    x: 120,
    y: -15,
    z: 42,
    mbti: "XXXX",
  });

  assert.deepEqual(saved, { x: 100, y: -15, z: 42, mbti: "INFJ" });
  assert.deepEqual(loadProfile(storage), saved);
});
