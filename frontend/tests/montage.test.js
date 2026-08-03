import test from "node:test";
import assert from "node:assert/strict";

import { createMontageSchedule } from "../src/lib/montage.js";

test("creates a deterministic silver-dream montage schedule", () => {
  assert.deepEqual(
    createMontageSchedule({ count: 20, seed: 25 }),
    createMontageSchedule({ count: 20, seed: 25 }),
  );
});

test("keeps memory fragments to thirty percent of the field", () => {
  const schedule = createMontageSchedule({ count: 20, seed: 25 });
  const memoryCount = schedule.filter(({ kind }) => kind === "memory").length;

  assert.equal(schedule.length, 20);
  assert.equal(memoryCount, 6);
});

test("keeps montage values normalized for canvas rendering", () => {
  const schedule = createMontageSchedule({ count: 32, seed: 9 });

  assert.ok(
    schedule.every(
      ({ x, y, scale, opacity, start, duration }) =>
        x >= 0 &&
        x <= 1 &&
        y >= 0 &&
        y <= 1 &&
        scale >= 0.3 &&
        scale <= 1.4 &&
        opacity >= 0.03 &&
        opacity <= 0.22 &&
        start >= 0 &&
        duration >= 2800,
    ),
  );
});
