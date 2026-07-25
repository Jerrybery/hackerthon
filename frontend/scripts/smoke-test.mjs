const baseUrl = process.env.PREVIEW_URL || "http://127.0.0.1:4173";

const checks = [
  ["/", "Persona.OS — Identity Matrix"],
  ["/src/main.js", "mountChatView"],
  ["/src/styles.css", ".crystal-chamber"],
  ["/src/components/crystal-field.js", "class CrystalField"],
  ["/src/components/persona-select-view.js", "projected-arm-layer"],
  ["/src/components/xyz-editor-view.js", "mountXyzEditor"],
  ["/src/components/chat-view.js", "mountChatView"],
  ["/node_modules/three/build/three.module.js", "WebGLRenderer"],
  ["/public/assets/v2/winter-silver-dream.png", null],
  ["/public/assets/v2/custom-silver-dream-arm.png", null],
  ["/public/assets/v3/johnny-exact.png", null],
  ["/public/assets/v3/jarvis-reactor.png", null],
  ["/public/assets/v3/crystal-chamber.png", null],
  ["/public/assets/v2/card-winter-memory.png", null],
  ["/public/assets/v2/card-johnny-noise.png", null],
  ["/public/assets/v2/card-jarvis-optics.png", null],
  ["/public/assets/v2/card-self-mercury.png", null],
];

for (const [path, expected] of checks) {
  const response = await fetch(`${baseUrl}${path}`);
  if (!response.ok) {
    throw new Error(`${path} returned ${response.status}`);
  }

  if (expected) {
    const content = await response.text();
    if (!content.includes(expected)) {
      throw new Error(`${path} did not include ${expected}`);
    }
  }
}

console.log(`Smoke test passed against ${baseUrl}`);
