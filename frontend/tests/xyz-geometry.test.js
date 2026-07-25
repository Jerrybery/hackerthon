import test from "node:test";
import assert from "node:assert/strict";

import {
  applyPlaneDrag,
  axisToPosition,
  createSpherePoints,
  getDepthCompensatedScale,
} from "../src/lib/xyz-geometry.js";

test("creates deterministic unit-sphere points", () => {
  const points = createSpherePoints({ count: 100, seed: 25 });

  assert.deepEqual(
    points,
    createSpherePoints({ count: 100, seed: 25 }),
  );
  assert.equal(points.length, 300);

  for (let index = 0; index < points.length; index += 3) {
    const radius = Math.hypot(
      points[index],
      points[index + 1],
      points[index + 2],
    );
    assert.ok(radius >= 0.88);
    assert.ok(radius <= 1.001);
  }
});

test("maps XYZ display values into the editor volume", () => {
  assert.deepEqual(
    axisToPosition({ x: 100, y: -50, z: 0 }),
    { x: 1, y: -0.5, z: 0 },
  );
});

test("clamps invalid axis positions", () => {
  assert.deepEqual(
    axisToPosition({ x: 220, y: Number.NaN, z: -400 }),
    { x: 1, y: 0, z: -1 },
  );
});

test("keeps the persona marker visually stable across the Z axis", () => {
  assert.equal(getDepthCompensatedScale({ z: 0, cameraZ: 4.65 }), 1);
  assert.equal(getDepthCompensatedScale({ z: 1, cameraZ: 4.65 }), 0.785);
  assert.equal(getDepthCompensatedScale({ z: -1, cameraZ: 4.65 }), 1.215);
});

test("falls back to a safe marker scale for invalid depth inputs", () => {
  assert.equal(getDepthCompensatedScale({ z: Number.NaN, cameraZ: 4.65 }), 1);
  assert.equal(getDepthCompensatedScale({ z: 0.5, cameraZ: 0 }), 1);
});

test("maps XZ screen drag continuously into X and Z values", () => {
  assert.deepEqual(
    applyPlaneDrag(
      { x: 10, y: 20, z: 0 },
      { plane: "xz", deltaX: 40, deltaY: -30, width: 400, height: 300 },
    ),
    { x: 37, y: 20, z: 20 },
  );
});

test("maps YZ screen drag continuously into Y and Z values", () => {
  assert.deepEqual(
    applyPlaneDrag(
      { x: 10, y: 20, z: 0 },
      { plane: "yz", deltaX: 50, deltaY: 30, width: 400, height: 300 },
    ),
    { x: 10, y: 0, z: 33 },
  );
});

test("clamps plane drag values instead of jumping beyond the profile range", () => {
  assert.deepEqual(
    applyPlaneDrag(
      { x: 90, y: -90, z: 90 },
      { plane: "xz", deltaX: 500, deltaY: -500, width: 400, height: 300 },
    ),
    { x: 100, y: -90, z: 100 },
  );
});
