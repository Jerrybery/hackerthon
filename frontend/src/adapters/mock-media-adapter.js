export function createMockMediaAdapter({
  delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds)),
} = {}) {
  let state = "idle";
  const listeners = new Set();

  function update(next) {
    state = next;
    listeners.forEach((listener) => listener(state));
  }

  return {
    getState: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    startRecording() {
      if (state !== "idle") return false;
      update("recording");
      return true;
    },
    async stopRecording() {
      if (state !== "recording") return "";
      update("transcribing");
      await delay(760);
      update("idle");
      return "你好，我想了解现在的人格状态。";
    },
  };
}
