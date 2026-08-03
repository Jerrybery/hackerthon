import test from "node:test";
import assert from "node:assert/strict";

import {
  getParticleBudget,
  getPerformanceTier,
} from "../src/lib/performance-tier.js";

test("caps high DPR devices to a normal particle budget", () => {
  assert.equal(
    getPerformanceTier({ hardwareConcurrency: 8, dpr: 3 }),
    "normal",
  );
  assert.equal(getParticleBudget("normal"), 2000);
});

test("uses the low tier for four or fewer logical cores", () => {
  assert.equal(
    getPerformanceTier({ hardwareConcurrency: 4, dpr: 1 }),
    "low",
  );
  assert.equal(getParticleBudget("low"), 1000);
});

test("uses the high tier only for capable standard-DPR devices", () => {
  assert.equal(
    getPerformanceTier({ hardwareConcurrency: 10, dpr: 2 }),
    "high",
  );
  assert.equal(getParticleBudget("high"), 4000);
});
