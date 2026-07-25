const STORAGE_KEY = "advx.selfPersona.v1";
const MBTI_TYPES = new Set([
  "INTJ", "INTP", "ENTJ", "ENTP",
  "INFJ", "INFP", "ENFJ", "ENFP",
  "ISTJ", "ISFJ", "ESTJ", "ESFJ",
  "ISTP", "ISFP", "ESTP", "ESFP",
]);

export const DEFAULT_PROFILE = Object.freeze({
  x: 0,
  y: 0,
  z: 0,
  mbti: "INFJ",
});

export function normalizeAxis(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 0;
  return Math.max(-100, Math.min(100, Math.round(numeric)));
}

export function toInternalAxis(value) {
  return normalizeAxis(value) / 100;
}

function normalizeProfile(profile = {}) {
  return {
    x: normalizeAxis(profile.x),
    y: normalizeAxis(profile.y),
    z: normalizeAxis(profile.z),
    mbti: MBTI_TYPES.has(profile.mbti) ? profile.mbti : DEFAULT_PROFILE.mbti,
  };
}

function describeAxis(value, negative, neutral, positive) {
  const magnitude = Math.abs(value);
  if (magnitude <= 20) return neutral;
  const intensity = magnitude > 80 ? "极强" : magnitude > 50 ? "强烈" : "明显";
  return `${intensity}${value < 0 ? negative : positive}`;
}

export function describeProfile(profile) {
  const normalized = normalizeProfile(profile);
  const affinity = describeAxis(
    normalized.x,
    "疏离，保持谨慎的关系距离",
    "自然而有分寸地回应",
    "温暖友善，并主动关心对方",
  );
  const rationality = describeAxis(
    normalized.y,
    "依赖感受与直觉组织判断",
    "在理性与感性之间保持平衡",
    "偏好理性分析和清晰依据",
  );
  const expression = describeAxis(
    normalized.z,
    "克制平静，表达简短",
    "采用自然稳定的表达强度",
    "活跃外放，表达更有情绪与节奏",
  );

  return `${normalized.mbti} · ${affinity}；${rationality}；${expression}。`;
}

export function loadProfile(storage) {
  try {
    const value = storage?.getItem?.(STORAGE_KEY);
    if (!value) return { ...DEFAULT_PROFILE };
    return normalizeProfile(JSON.parse(value));
  } catch {
    return { ...DEFAULT_PROFILE };
  }
}

export function saveProfile(storage, profile) {
  const normalized = normalizeProfile(profile);
  try {
    storage?.setItem?.(STORAGE_KEY, JSON.stringify(normalized));
  } catch {
    return normalized;
  }
  return normalized;
}
