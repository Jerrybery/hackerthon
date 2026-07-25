import test from "node:test";
import assert from "node:assert/strict";

import { APP_MODES, createAppState } from "../src/lib/app-state.js";

test("opens chat with the selected persona", () => {
  const app = createAppState({ personaId: "winter" });

  app.openChat();

  assert.equal(app.getState().mode, APP_MODES.CHAT);
  assert.equal(app.getState().personaId, "winter");
});

test("opens XYZ only after create confirmation", () => {
  const app = createAppState();

  app.openEditor();
  assert.equal(app.getState().mode, APP_MODES.XYZ_EDITOR);

  app.closeWorkspace();
  assert.equal(app.getState().mode, APP_MODES.PERSONA_SELECT);
});

test("notifies subscribers with immutable state snapshots", () => {
  const app = createAppState();
  const snapshots = [];
  const unsubscribe = app.subscribe((state) => snapshots.push(state));

  app.selectPersona("johnny");
  unsubscribe();
  app.selectPersona("winter");

  assert.equal(snapshots.length, 1);
  assert.equal(snapshots[0].personaId, "johnny");
  assert.notEqual(snapshots[0], app.getState());
});

test("does not notify subscribers when a value is unchanged", () => {
  const app = createAppState({ personaId: "custom" });
  let notifications = 0;
  app.subscribe(() => { notifications += 1; });

  app.selectPersona("custom");

  assert.equal(notifications, 0);
});
