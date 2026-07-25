import test from "node:test";
import assert from "node:assert/strict";

import { createParticles } from "../src/lib/particles.js";

test("creates deterministic particle data for a seed", () => {
  assert.deepEqual(
    createParticles({ count: 3, width: 800, height: 600, seed: 9 }),
    createParticles({ count: 3, width: 800, height: 600, seed: 9 }),
  );
});

test("keeps particles inside the viewport with normalized depth", () => {
  const particles = createParticles({
    count: 64,
    width: 1440,
    height: 900,
    seed: 42,
  });

  assert.equal(particles.length, 64);
  assert.ok(
    particles.every(
      ({ x, y, depth }) =>
        x >= 0 &&
        x <= 1440 &&
        y >= 0 &&
        y <= 900 &&
        depth >= 0.2 &&
        depth <= 1,
    ),
  );
});

test("returns no particles for an empty or invalid field", () => {
  assert.deepEqual(createParticles({ count: 0, width: 100, height: 100 }), []);
  assert.deepEqual(createParticles({ count: 10, width: 0, height: 100 }), []);
});
