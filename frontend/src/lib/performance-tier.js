export function getPerformanceTier({
  hardwareConcurrency = 4,
  dpr = 1,
} = {}) {
  if (hardwareConcurrency <= 4) return "low";
  if (hardwareConcurrency >= 8 && dpr <= 2) return "high";
  return "normal";
}

export function getParticleBudget(tier) {
  return {
    high: 4000,
    normal: 2000,
    low: 1000,
  }[tier] ?? 1000;
}
