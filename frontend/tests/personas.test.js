import test from "node:test";
import assert from "node:assert/strict";

import { PERSONAS, getPersona } from "../src/lib/personas.js";

test("defines four personas with versioned local hero and card assets", () => {
  assert.equal(PERSONAS.length, 4);
  assert.ok(
    PERSONAS.every(
      ({ heroImage, cardImage }) =>
        /^\/public\/assets\/v[23]\//.test(heroImage) &&
        cardImage.startsWith("/public/assets/v2/"),
    ),
  );
});

test("uses a distinct editorial image for every persona card", () => {
  const cardImages = PERSONAS.map(({ cardImage }) => cardImage);
  assert.equal(new Set(cardImages).size, PERSONAS.length);
});

test("only the custom persona allows a spectral arm", () => {
  assert.deepEqual(
    PERSONAS.filter(({ allowsSpectralArm }) => allowsSpectralArm).map(({ id }) => id),
    ["custom"],
  );
  assert.equal(getPersona("winter").name, "冬兵");
});

test("uses the user-specified Johnny and Jarvis v3 hero assets", () => {
  assert.equal(getPersona("johnny").heroImage, "/public/assets/v3/johnny-exact.png");
  assert.equal(getPersona("jarvis").heroImage, "/public/assets/v3/jarvis-reactor.png");
});
