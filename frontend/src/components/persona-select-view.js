import { ParticleField } from "./particle-field.js";
import { getCardVisualState, normalizePointer } from "../lib/interaction.js";
import { PERSONAS, getPersona } from "../lib/personas.js";

const cardMarkup = PERSONAS
  .map(
    (persona, index) => `
      <button
        class="persona-card ${persona.id === "custom" ? "is-active" : ""}"
        type="button"
        data-persona="${persona.id}"
        data-index="${index}"
        aria-pressed="${persona.id === "custom"}"
      >
        <span class="card-art">
          <img src="${persona.cardImage}" alt="" aria-hidden="true" />
          <span class="card-refraction" aria-hidden="true"></span>
          <span class="card-grain" aria-hidden="true"></span>
        </span>
        <span class="card-coordinate">P-${persona.number} / ${String(721 + index * 118).padStart(4, "0")}</span>
        <span class="card-copy">
          <span>
            <small>${persona.role}</small>
            <strong>${persona.name}</strong>
          </span>
        </span>
        <span class="card-arrow" aria-hidden="true">↗</span>
        <span class="card-index" aria-hidden="true">${persona.number}</span>
      </button>
    `,
  )
  .join("");

export function mountPersonaSelect({ root, appState }) {
root.innerHTML = `
  <div class="interface-shell" data-active-persona="custom">
    <div class="crystal-chamber" aria-hidden="true"></div>
    <canvas class="particle-field" aria-hidden="true"></canvas>
    <div class="mirror-array" aria-hidden="true">
      <i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i>
    </div>
    <div class="mirror-lake" aria-hidden="true">
      <i class="lake-ripple lake-ripple--one"></i>
      <i class="lake-ripple lake-ripple--two"></i>
      <i class="lake-caustics"></i>
    </div>
    <div class="exposure-sweeps" aria-hidden="true">
      <i></i><i></i><i></i>
    </div>
    <div class="scan-noise" aria-hidden="true"></div>

    <header class="topbar">
      <a class="brand" href="#" aria-label="Persona OS 首页">
        <span class="brand-mark"><i></i><i></i><i></i></span>
        <span><strong>AD·VX</strong><small>PERSONA OPERATING SYSTEM</small></span>
      </a>
      <div class="system-line" aria-label="系统状态">
        <span><i class="pulse-dot"></i> CORE ONLINE</span>
        <span>LOCAL / 001</span>
        <span>SHANGHAI <b id="system-clock">02:57:24</b></span>
      </div>
      <button class="sound-toggle" type="button" aria-label="切换环境音" aria-pressed="false">
        <span></span><span></span><span></span><span></span>
        <small>AMBIENCE OFF</small>
      </button>
    </header>

    <aside class="left-rail" aria-label="当前界面">
      <span>IDENTITY MATRIX</span>
      <i></i>
      <small>04 / 07</small>
    </aside>

    <section class="intro-block" aria-labelledby="interface-title">
      <p class="section-kicker"><span></span> SELECT CONSCIOUSNESS</p>
      <h1 id="interface-title" class="silver-title" aria-label="选择一个意识载体">
        <span class="silver-title__base">选择一个<br /><em>意识载体</em></span>
        <span class="silver-title__sheen" aria-hidden="true">选择一个<br /><em>意识载体</em></span>
      </h1>
      <p class="intro-copy">人格不是头像，而是一种持续响应你的存在方式。</p>
      <div class="intro-meta">
        <span>4 SHELLS AVAILABLE</span>
        <span>POINTER REACTIVE</span>
      </div>
    </section>

    <section class="identity-matrix" aria-label="选择人格">
      ${cardMarkup}
    </section>

    <section class="hero-stage" aria-live="polite">
      <div class="hero-orbit hero-orbit--outer" aria-hidden="true"></div>
      <div class="hero-orbit hero-orbit--inner" aria-hidden="true"></div>
      <div class="hero-backlight" aria-hidden="true"></div>
      <div class="jarvis-optics" aria-hidden="true"><i></i><i></i><i></i></div>
      <div class="hero-film-flash" aria-hidden="true"></div>

      <div class="hero-figure" data-hero-kind="custom">
        <div class="hero-image-wrap">
          <img
            class="hero-image hero-image--base"
            src="/public/assets/v2/custom-silver-dream-arm.png"
            alt="自我人格的人格形象"
          />
          <span class="hero-silver-sweep" aria-hidden="true"></span>
        </div>
      </div>

      <div class="hero-index" aria-hidden="true">
        <span id="hero-number">04</span>
        <i></i>
        <small>SELECTED SHELL</small>
      </div>

      <div class="hero-caption">
        <p id="hero-role">可塑身份体</p>
        <h2><span id="hero-name">自我人格</span><small id="hero-english">SELF / LIQUID CHROME</small></h2>
        <div class="hero-status">
          <span><i></i><b id="hero-status">IDENTITY SHELL READY</b></span>
          <span id="hero-signature">MALLEABLE CORE / SPECTRAL ARM</span>
        </div>
        <p id="hero-note">身体保持冷冽黑银，只有伸向屏幕的机械前臂承载流彩反射。</p>
      </div>
    </section>

    <div class="projected-arm-layer" aria-hidden="true">
      <img src="/public/assets/v2/custom-silver-dream-arm.png" alt="" />
      <span></span>
    </div>

    <div class="edge-readout edge-readout--top" aria-hidden="true">
      <span>AZ 217.4°</span><span>EL +08.2°</span><span>SYNC 98.7</span>
    </div>
    <div class="edge-readout edge-readout--side" aria-hidden="true">
      <span>NEURAL LINK</span><i></i><span>STABLE</span>
    </div>

    <footer class="action-dock">
      <button class="enter-button" type="button">
        <span>进入对话</span>
        <small>ENTER CONVERSATION</small>
        <i aria-hidden="true">→</i>
      </button>
      <button class="add-button" type="button" aria-haspopup="dialog">
        <span aria-hidden="true">＋</span>
        <p>新增人格<small>CREATE PERSONA</small></p>
      </button>
    </footer>

    <div class="creation-gate" role="dialog" aria-modal="true" aria-labelledby="creation-title" hidden>
      <button class="gate-backdrop" type="button" aria-label="关闭新增人格面板"></button>
      <section>
        <button class="gate-close" type="button" aria-label="关闭">×</button>
        <p class="section-kicker"><span></span> NEW CONSCIOUSNESS</p>
        <small>PRE-CALIBRATION / 00</small>
        <h2 id="creation-title">准备构建一个<br /><em>新的身份壳层？</em></h2>
        <p>确认后才会进入 XYZ 粒子坐标校准。当前版本停在确认门，不让坐标轴提前占据主界面。</p>
        <div class="gate-spec">
          <span><b>X</b> INTENT</span>
          <span><b>Y</b> TEMPER</span>
          <span><b>Z</b> BOUNDARY</span>
        </div>
        <button class="gate-confirm" type="button">
          <span>确认建立</span>
          <small>XYZ CALIBRATION — NEXT PHASE</small>
        </button>
      </section>
    </div>

  </div>
`;

const shell = root.querySelector(".interface-shell");
const particleField = new ParticleField(root.querySelector(".particle-field"));
const cards = [...root.querySelectorAll(".persona-card")];
const heroFigure = root.querySelector(".hero-figure");
const heroImage = root.querySelector(".hero-image--base");
const projectedArm = root.querySelector(".projected-arm-layer img");
const clock = root.querySelector("#system-clock");
const creationGate = root.querySelector(".creation-gate");
let personaTimer;

function updateClock() {
  clock.textContent = new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date());
}

function commitPersona(persona) {
  shell.dataset.activePersona = persona.id;
  heroFigure.dataset.heroKind = persona.id;
  heroImage.src = persona.heroImage;
  heroImage.alt = `${persona.name}的人格形象`;
  projectedArm.src = persona.heroImage;

  root.querySelector("#hero-number").textContent = persona.number;
  root.querySelector("#hero-role").textContent = persona.role;
  root.querySelector("#hero-name").textContent = persona.name;
  root.querySelector("#hero-english").textContent = persona.english;
  root.querySelector("#hero-status").textContent = persona.status;
  root.querySelector("#hero-signature").textContent = persona.signature;
  root.querySelector("#hero-note").textContent = persona.note;
  appState.selectPersona(persona.id);

  cards.forEach((card) => {
    const selected = card.dataset.persona === persona.id;
    card.classList.toggle("is-active", selected);
    card.setAttribute("aria-pressed", String(selected));
  });
}

function selectPersona(id, { immediate = false } = {}) {
  const persona = getPersona(id);
  if (!persona) return;

  window.clearTimeout(personaTimer);
  shell.classList.add("is-developing");

  if (immediate) {
    commitPersona(persona);
    shell.classList.remove("is-developing");
    return;
  }

  personaTimer = window.setTimeout(() => {
    commitPersona(persona);
    shell.classList.remove("is-developing");
  }, 180);
}

cards.forEach((card) => {
  const index = Number(card.dataset.index);

  card.addEventListener("pointermove", (event) => {
    const pointer = normalizePointer(event.clientX, event.clientY, card.getBoundingClientRect());
    const visual = getCardVisualState(index, pointer);
    card.classList.add("is-hovered");
    card.style.setProperty("--card-hue", visual.hue);
    card.style.setProperty("--light-x", `${visual.lightX}%`);
    card.style.setProperty("--light-y", `${visual.lightY}%`);
    card.style.setProperty("--tilt-x", `${visual.tiltX}deg`);
    card.style.setProperty("--tilt-y", `${visual.tiltY}deg`);
  });

  card.addEventListener("pointerleave", () => {
    card.classList.remove("is-hovered");
    card.style.removeProperty("--light-x");
    card.style.removeProperty("--light-y");
    card.style.removeProperty("--tilt-x");
    card.style.removeProperty("--tilt-y");
  });

  card.addEventListener("click", () => selectPersona(card.dataset.persona));
});

function handlePointerMove(event) {
  const x = event.clientX / window.innerWidth - 0.5;
  const y = event.clientY / window.innerHeight - 0.5;
  shell.style.setProperty("--pointer-x", x.toFixed(3));
  shell.style.setProperty("--pointer-y", y.toFixed(3));
  shell.style.setProperty("--arm-hue", `${Math.round(205 + event.clientX / window.innerWidth * 190)}deg`);
  particleField.setPointer(x, y);
}

window.addEventListener("pointermove", handlePointerMove, { passive: true });

root.querySelector(".sound-toggle").addEventListener("click", (event) => {
  const button = event.currentTarget;
  const enabled = button.getAttribute("aria-pressed") !== "true";
  button.setAttribute("aria-pressed", String(enabled));
  button.querySelector("small").textContent = enabled ? "AMBIENCE ON" : "AMBIENCE OFF";
});

function setGate(open) {
  creationGate.hidden = !open;
  document.body.classList.toggle("has-dialog", open);
  if (open) {
    requestAnimationFrame(() => creationGate.classList.add("is-visible"));
    creationGate.querySelector(".gate-close").focus();
  } else {
    creationGate.classList.remove("is-visible");
  }
}

root.querySelector(".enter-button").addEventListener("click", () => appState.openChat());
root.querySelector(".add-button").addEventListener("click", () => setGate(true));
root.querySelector(".gate-close").addEventListener("click", () => setGate(false));
root.querySelector(".gate-backdrop").addEventListener("click", () => setGate(false));
root.querySelector(".gate-confirm").addEventListener("click", () => {
  setGate(false);
  appState.openEditor();
});

function handleKeydown(event) {
  if (event.key === "Escape" && !creationGate.hidden) {
    setGate(false);
  }
}

document.addEventListener("keydown", handleKeydown);

updateClock();
const clockTimer = window.setInterval(updateClock, 1000);
selectPersona(appState.getState().personaId, { immediate: true });

return () => {
  window.clearInterval(clockTimer);
  window.clearTimeout(personaTimer);
  window.removeEventListener("pointermove", handlePointerMove);
  document.removeEventListener("keydown", handleKeydown);
  particleField.destroy();
  document.body.classList.remove("has-dialog");
};
}
