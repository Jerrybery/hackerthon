import test from "node:test";
import assert from "node:assert/strict";

import {
  getCardVisualState,
  normalizePointer,
} from "../src/lib/interaction.js";

test("normalizes the pointer around the card center", () => {
  const rect = { left: 100, top: 50, width: 200, height: 100 };

  assert.deepEqual(normalizePointer(200, 100, rect), { x: 0, y: 0 });
  assert.deepEqual(normalizePointer(100, 50, rect), { x: -1, y: -1 });
  assert.deepEqual(normalizePointer(300, 150, rect), { x: 1, y: 1 });
});

test("clamps pointer values outside the card", () => {
  const rect = { left: 0, top: 0, width: 100, height: 100 };

  assert.deepEqual(normalizePointer(-20, 140, rect), { x: -1, y: 1 });
});

test("derives a stable but pointer-reactive visual state", () => {
  assert.deepEqual(getCardVisualState(0, { x: 0, y: 0 }), {
    hue: 188,
    lightX: 50,
    lightY: 50,
    tiltX: 0,
    tiltY: 0,
  });

  assert.deepEqual(getCardVisualState(2, { x: 0.5, y: -0.5 }), {
    hue: 291,
    lightX: 75,
    lightY: 25,
    tiltX: 2,
    tiltY: 2.5,
  });
});
