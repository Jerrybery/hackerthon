function createRandom(seed) {
  let state = seed >>> 0;

  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 4294967296;
  };
}

export function createMontageSchedule({ count = 20, seed = 25 } = {}) {
  if (!Number.isFinite(count) || count <= 0) return [];

  const total = Math.floor(count);
  const random = createRandom(seed);
  const memoryCount = Math.round(total * 0.3);
  const kinds = Array.from({ length: total }, (_, index) =>
    index < memoryCount ? "memory" : index % 3 === 0 ? "bloom" : "ribbon",
  );

  for (let index = kinds.length - 1; index > 0; index -= 1) {
    const target = Math.floor(random() * (index + 1));
    [kinds[index], kinds[target]] = [kinds[target], kinds[index]];
  }

  return kinds.map((kind, index) => ({
    kind,
    x: random(),
    y: random(),
    scale: 0.3 + random() * 1.1,
    opacity: 0.03 + random() * 0.19,
    start: Math.round(random() * 9000),
    duration: Math.round(2800 + random() * 6200),
    phase: random() * Math.PI * 2 + index * 0.13,
  }));
}
