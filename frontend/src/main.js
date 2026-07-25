import { APP_MODES, createAppState } from "./lib/app-state.js";
import { mountChatView } from "./components/chat-view.js";
import { mountPersonaSelect } from "./components/persona-select-view.js";
import { runViewTransition } from "./components/transition-layer.js";
import { mountXyzEditor } from "./components/xyz-editor-view.js";
import { loadProfile } from "./lib/persona-profile.js";

const root = document.querySelector("#app");
const appState = createAppState({
  personaId: "custom",
  profile: loadProfile(window.localStorage),
});
let cleanupView = () => {};
let activeMode = null;

function mountMode(state) {
  if (state.mode === activeMode) return;
  cleanupView();
  activeMode = state.mode;

  if (state.mode === APP_MODES.XYZ_EDITOR) {
    cleanupView = mountXyzEditor({ root, appState });
    return;
  }
  if (state.mode === APP_MODES.CHAT) {
    cleanupView = mountChatView({ root, appState });
    return;
  }
  cleanupView = mountPersonaSelect({ root, appState });
}

let transition = Promise.resolve();

function render(state) {
  if (activeMode === null) {
    mountMode(state);
    return;
  }
  if (state.mode === activeMode) return;

  transition = transition.then(() => runViewTransition({
    root,
    render: () => mountMode(state),
  }));
}

appState.subscribe(render);
mountMode(appState.getState());
