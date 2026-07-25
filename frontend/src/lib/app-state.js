export const APP_MODES = Object.freeze({
  PERSONA_SELECT: "PERSONA_SELECT",
  XYZ_EDITOR: "XYZ_EDITOR",
  CHAT: "CHAT",
});

export function createAppState(initial = {}) {
  let state = {
    mode: APP_MODES.PERSONA_SELECT,
    personaId: initial.personaId ?? "custom",
    profile: initial.profile ?? null,
  };
  const listeners = new Set();

  function update(patch) {
    const changed = Object.entries(patch).some(
      ([key, value]) => state[key] !== value,
    );
    if (!changed) return;
    state = { ...state, ...patch };
    listeners.forEach((listener) => listener({ ...state }));
  }

  return {
    getState: () => ({ ...state }),
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    selectPersona(personaId) {
      update({ personaId });
    },
    openChat() {
      update({ mode: APP_MODES.CHAT });
    },
    openEditor() {
      update({ mode: APP_MODES.XYZ_EDITOR });
    },
    closeWorkspace() {
      update({ mode: APP_MODES.PERSONA_SELECT });
    },
    saveProfile(profile) {
      update({
        profile: { ...profile },
        personaId: "custom",
        mode: APP_MODES.CHAT,
      });
    },
  };
}
