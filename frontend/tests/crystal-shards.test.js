import test from "node:test";
import assert from "node:assert/strict";

import { createCrystalShards } from "../src/lib/crystal-shards.js";

test("creates deterministic crystal shards across three depth groups", () => {
  const shards = createCrystalShards({ count: 30, seed: 25 });

  assert.deepEqual(shards, createCrystalShards({ count: 30, seed: 25 }));
  assert.deepEqual([...new Set(shards.map(({ depth }) => depth))].sort(), [0, 1, 2]);
});

test("keeps shard geometry and motion inside configured ranges", () => {
  const shards = createCrystalShards({ count: 48, seed: 9 });

  assert.ok(
    shards.every(
      ({ x, y, width, height, speed, opacity, blur }) =>
        x >= 0 &&
        x <= 1 &&
        y >= 0 &&
        y <= 1 &&
        width >= 0.008 &&
        width <= 0.07 &&
        height >= 0.08 &&
        height <= 0.42 &&
        speed >= 0.000006 &&
        speed <= 0.000024 &&
        opacity >= 0.05 &&
        opacity <= 0.28 &&
        blur >= 0 &&
        blur <= 5,
    ),
  );
});

test("returns no shards for invalid counts", () => {
  assert.deepEqual(createCrystalShards({ count: 0, seed: 25 }), []);
  assert.deepEqual(createCrystalShards({ count: -4, seed: 25 }), []);
});
