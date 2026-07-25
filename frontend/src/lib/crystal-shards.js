function createRandom(seed) {
  let state = seed >>> 0;

  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 4294967296;
  };
}

export function createCrystalShards({ count = 32, seed = 25 } = {}) {
  if (!Number.isFinite(count) || count <= 0) return [];

  const random = createRandom(seed);

  return Array.from({ length: Math.floor(count) }, (_, index) => {
    const depth = index % 3;
    const depthProgress = depth / 2;

    return {
      depth,
      x: random(),
      y: random(),
      width: 0.008 + random() * 0.062,
      height: 0.08 + random() * 0.34,
      speed: 0.000006 + random() * 0.000018,
      tilt: -0.19 + random() * 0.38,
      opacity: 0.05 + random() * 0.23,
      blur: (1 - depthProgress) * 5 * random(),
      phase: random() * Math.PI * 2,
    };
  });
}
