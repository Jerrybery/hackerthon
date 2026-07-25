import test from "node:test";
import assert from "node:assert/strict";

import { createIdleScheduler } from "../src/lib/idle-scheduler.js";

test("stops scheduling after the activity window expires", () => {
  let frames = 0;
  const scheduler = createIdleScheduler({
    duration: 800,
    requestFrame(callback) {
      frames += 1;
      callback(900);
      return frames;
    },
    cancelFrame() {},
  });

  scheduler.wake(0);

  assert.equal(frames, 1);
  assert.equal(scheduler.isAwake(), false);
});

test("renders a static frame without starting a loop", () => {
  let renders = 0;
  const scheduler = createIdleScheduler({
    render: () => { renders += 1; },
    requestFrame: () => {
      throw new Error("static render should not schedule a frame");
    },
    cancelFrame() {},
  });

  scheduler.renderOnce(25);

  assert.equal(renders, 1);
  assert.equal(scheduler.isAwake(), false);
});

test("stop cancels the pending frame", () => {
  let cancelled;
  const scheduler = createIdleScheduler({
    render: () => {},
    requestFrame: () => 42,
    cancelFrame: (frame) => { cancelled = frame; },
  });

  scheduler.wake(0);
  scheduler.stop();

  assert.equal(cancelled, 42);
  assert.equal(scheduler.isAwake(), false);
});
