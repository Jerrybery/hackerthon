const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

const BASE_HUES = [188, 20, 278, 154];

export function normalizePointer(clientX, clientY, rect) {
  const x = ((clientX - rect.left) / rect.width) * 2 - 1;
  const y = ((clientY - rect.top) / rect.height) * 2 - 1;

  return {
    x: clamp(x, -1, 1),
    y: clamp(y, -1, 1),
  };
}

export function getCardVisualState(index, pointer) {
  const baseHue = BASE_HUES[index % BASE_HUES.length];

  return {
    hue: Math.round(baseHue + pointer.x * 18 - pointer.y * 8),
    lightX: Math.round((pointer.x + 1) * 50),
    lightY: Math.round((pointer.y + 1) * 50),
    tiltX: Number((-pointer.y * 4).toFixed(2)),
    tiltY: Number((pointer.x * 5).toFixed(2)),
  };
}
