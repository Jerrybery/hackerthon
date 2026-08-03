import { normalizeAxis } from "./persona-profile.js";

function createRandom(seed) {
  let value = seed >>> 0;
  return () => {
    value += 0x6d2b79f5;
    let result = value;
    result = Math.imul(result ^ (result >>> 15), result | 1);
    result ^= result + Math.imul(result ^ (result >>> 7), result | 61);
    return ((result ^ (result >>> 14)) >>> 0) / 4294967296;
  };
}

export function createSpherePoints({ count = 1000, seed = 25 } = {}) {
  const safeCount = Math.max(0, Math.floor(count));
  const positions = new Float32Array(safeCount * 3);
  const random = createRandom(seed);
  const goldenAngle = Math.PI * (3 - Math.sqrt(5));

  for (let index = 0; index < safeCount; index += 1) {
    const progress = (index + 0.5) / safeCount;
    const y = 1 - progress * 2;
    const horizontalRadius = Math.sqrt(Math.max(0, 1 - y * y));
    const angle = index * goldenAngle;
    const radialJitter = 0.88 + random() * 0.12;
    const offset = index * 3;

    positions[offset] = Math.cos(angle) * horizontalRadius * radialJitter;
    positions[offset + 1] = y * radialJitter;
    positions[offset + 2] = Math.sin(angle) * horizontalRadius * radialJitter;
  }

  return positions;
}

export function axisToPosition({ x = 0, y = 0, z = 0 } = {}) {
  return {
    x: normalizeAxis(x) / 100,
    y: normalizeAxis(y) / 100,
    z: normalizeAxis(z) / 100,
  };
}

export function getDepthCompensatedScale({ z = 0, cameraZ = 4.65 } = {}) {
  const numericDepth = Number(z);
  const numericCamera = Number(cameraZ);
  if (!Number.isFinite(numericDepth) || !Number.isFinite(numericCamera) || numericCamera <= 1) {
    return 1;
  }

  const safeDepth = Math.max(-1, Math.min(1, numericDepth));
  return Number(((numericCamera - safeDepth) / numericCamera).toFixed(3));
}

export function applyPlaneDrag(
  profile = {},
  {
    plane = "xy",
    deltaX = 0,
    deltaY = 0,
    width = 1,
    height = 1,
  } = {},
) {
  const next = {
    x: normalizeAxis(profile.x),
    y: normalizeAxis(profile.y),
    z: normalizeAxis(profile.z),
  };
  const span = Math.max(160, Math.min(Number(width) || 1, Number(height) || 1));
  const unitsPerPixel = 200 / span;
  const horizontal = (Number(deltaX) || 0) * unitsPerPixel;
  const vertical = -(Number(deltaY) || 0) * unitsPerPixel;

  if (plane === "xy" || plane === "xz") next.x = normalizeAxis(next.x + horizontal);
  if (plane === "xy" || plane === "yz") next.y = normalizeAxis(next.y + vertical);
  if (plane === "xz") next.z = normalizeAxis(next.z + vertical);
  if (plane === "yz") next.z = normalizeAxis(next.z + horizontal);

  return next;
}
