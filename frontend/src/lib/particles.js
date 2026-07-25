function mulberry32(seed) {
  let value = seed >>> 0;

  return () => {
    value += 0x6d2b79f5;
    let result = value;
    result = Math.imul(result ^ (result >>> 15), result | 1);
    result ^= result + Math.imul(result ^ (result >>> 7), result | 61);
    return ((result ^ (result >>> 14)) >>> 0) / 4294967296;
  };
}

export function createParticles({
  count,
  width,
  height,
  seed = 721,
}) {
  if (count <= 0 || width <= 0 || height <= 0) {
    return [];
  }

  const random = mulberry32(seed);

  return Array.from({ length: count }, (_, index) => ({
    x: random() * width,
    y: random() * height,
    depth: 0.2 + random() * 0.8,
    drift: (random() - 0.5) * 0.18,
    phase: random() * Math.PI * 2,
    kind: index % 11 === 0 ? "axis" : index % 5 === 0 ? "ember" : "dust",
  }));
}
