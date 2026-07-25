export function createIdleScheduler({
  duration = 800,
  render = () => {},
  requestFrame = (callback) => requestAnimationFrame(callback),
  cancelFrame = (frame) => cancelAnimationFrame(frame),
} = {}) {
  let awake = false;
  let deadline = 0;
  let frameId = null;

  function tick(time) {
    render(time);

    if (time >= deadline) {
      awake = false;
      frameId = null;
      return;
    }

    frameId = requestFrame(tick);
  }

  return {
    wake(time = 0) {
      deadline = Math.max(deadline, time + duration);
      if (awake) return;
      awake = true;
      frameId = requestFrame(tick);
    },
    renderOnce(time = 0) {
      render(time);
    },
    stop() {
      if (frameId !== null) cancelFrame(frameId);
      frameId = null;
      awake = false;
      deadline = 0;
    },
    isAwake() {
      return awake;
    },
  };
}
