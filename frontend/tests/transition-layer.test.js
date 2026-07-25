import test from "node:test";
import assert from "node:assert/strict";

import { getTransitionTiming } from "../src/components/transition-layer.js";

test("places the view swap before the transition completes", () => {
  assert.deepEqual(getTransitionTiming(600), {
    swapAt: 270,
    endAt: 600,
  });
});

test("uses a safe minimum duration", () => {
  assert.deepEqual(getTransitionTiming(100), {
    swapAt: 90,
    endAt: 200,
  });
});
