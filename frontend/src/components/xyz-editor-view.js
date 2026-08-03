import { XYZParticleSpace } from "./xyz-particle-space.js";
import {
  DEFAULT_PROFILE,
  describeProfile,
  loadProfile,
  saveProfile,
} from "../lib/persona-profile.js";

const AXES = [
  { key: "x", name: "亲和度", negative: "疏离", positive: "温暖" },
  { key: "y", name: "理性度", negative: "感性", positive: "理性" },
  { key: "z", name: "表现力", negative: "克制", positive: "活跃" },
];

const MBTI_TYPES = [
  "INTJ", "INTP", "ENTJ", "ENTP",
  "INFJ", "INFP", "ENFJ", "ENFP",
  "ISTJ", "ISFJ", "ESTJ", "ESFJ",
  "ISTP", "ISFP", "ESTP", "ESFP",
];

function sliderMarkup(axis, profile) {
  const value = profile[axis.key];
  const state = value <= -34 ? axis.negative : value >= 34 ? axis.positive : "均衡";
  return `
    <label class="axis-control" data-axis="${axis.key}">
      <span class="axis-control__head">
        <b>${axis.key.toUpperCase()}</b>
        <span>${axis.name}</span>
        <span class="axis-control__reading"><output>${value}</output><i>${state}</i></span>
      </span>
      <input type="range" min="-100" max="100" step="1" value="${value}" />
      <span class="axis-control__ends"><small>−100 ${axis.negative}</small><small>0 均衡</small><small>+100 ${axis.positive}</small></span>
      ${axis.key === "z" ? '<span class="axis-control__depth-note"><i></i> DEPTH MARKER STABILIZED</span>' : ""}
    </label>
  `;
}

export function mountXyzEditor({ root, appState }) {
  let draft = {
    ...DEFAULT_PROFILE,
    ...loadProfile(window.localStorage),
    ...appState.getState().profile,
  };

  root.innerHTML = `
    <section class="xyz-workspace">
      <div class="xyz-noise" aria-hidden="true"></div>
      <header class="workspace-topbar">
        <button class="workspace-back" type="button"><span>←</span> 返回人格矩阵</button>
        <div class="workspace-brand"><b>AD·VX</b><small>PERSONA FABRICATION LAB</small></div>
        <p><i></i> CALIBRATION ONLINE <span>02 / 04</span></p>
      </header>

      <section class="xyz-intro">
        <p>NEW CONSCIOUSNESS / COORDINATE CALIBRATION</p>
        <h1>塑造你的<br /><em>意识坐标</em></h1>
        <span>拖动光点改变人格倾向，拖动粒子空间旋转视角。</span>
      </section>

      <div class="xyz-stage">
        <div class="xyz-canvas-host"></div>
        <span class="axis-tag axis-tag--x">X · AFFINITY</span>
        <span class="axis-tag axis-tag--y">Y · RATIONALITY</span>
        <span class="axis-tag axis-tag--z">Z · EXPRESSION</span>
        <div class="plane-selector" aria-label="选择人格点拖动平面">
          <button class="is-active" type="button" data-plane="xy">XY</button>
          <button type="button" data-plane="xz">XZ</button>
          <button type="button" data-plane="yz">YZ</button>
        </div>
        <p class="xyz-readout">ACTIVE PLANE <b>XY</b><span>←→ X / ↑↓ Y · 空白处旋转</span></p>
      </div>

      <aside class="xyz-controls">
        <div class="xyz-controls__heading">
          <p>PERSONA VECTOR</p>
          <span>精确校准</span>
        </div>
        <div class="axis-controls">
          ${AXES.map((axis) => sliderMarkup(axis, draft)).join("")}
        </div>
        <div class="profile-summary">
          <small>LIVE PERSONA DESCRIPTION</small>
          <p>${describeProfile(draft)}</p>
        </div>
      </aside>

      <footer class="xyz-footer">
        <section class="mbti-picker">
          <div><small>COGNITIVE FRAME</small><strong>MBTI</strong></div>
          <div class="mbti-grid">
            ${MBTI_TYPES.map((type) => `
              <button class="${type === draft.mbti ? "is-active" : ""}" type="button" data-mbti="${type}">${type}</button>
            `).join("")}
          </div>
        </section>
        <button class="reset-profile" type="button">恢复均衡<small>RESET VECTOR</small></button>
        <button class="save-profile" type="button">
          <span>保存并进入对话</span>
          <small>COMMIT PERSONA</small>
          <i>→</i>
        </button>
      </footer>
    </section>
  `;

  const particleSpace = new XYZParticleSpace(
    root.querySelector(".xyz-canvas-host"),
    draft,
  );
  const summary = root.querySelector(".profile-summary p");

  function renderDraft() {
    for (const axis of AXES) {
      const control = root.querySelector(`[data-axis="${axis.key}"]`);
      control.querySelector("input").value = String(draft[axis.key]);
      control.querySelector("output").value = String(draft[axis.key]);
      control.querySelector(".axis-control__reading i").textContent =
        draft[axis.key] <= -34 ? axis.negative : draft[axis.key] >= 34 ? axis.positive : "均衡";
      control.dataset.polarity =
        draft[axis.key] <= -34 ? "negative" : draft[axis.key] >= 34 ? "positive" : "balanced";
      control.style.setProperty("--axis-value", `${(draft[axis.key] + 100) / 2}%`);
    }
    summary.textContent = describeProfile(draft);
    root.querySelectorAll("[data-mbti]").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.mbti === draft.mbti);
    });
    particleSpace.setProfile(draft);
  }

  particleSpace.setOnProfileChange((profile) => {
    draft = { ...draft, ...profile };
    renderDraft();
  });

  root.querySelectorAll(".axis-control input").forEach((input) => {
    input.addEventListener("input", () => {
      const axis = input.closest(".axis-control").dataset.axis;
      draft = { ...draft, [axis]: Number(input.value) };
      renderDraft();
    });
  });

  root.querySelectorAll("[data-plane]").forEach((button) => {
    button.addEventListener("click", () => {
      particleSpace.setActivePlane(button.dataset.plane);
      root.querySelectorAll("[data-plane]").forEach((item) => {
        item.classList.toggle("is-active", item === button);
      });
      root.querySelector(".xyz-readout b").textContent = button.dataset.plane.toUpperCase();
      root.querySelector(".xyz-readout span").textContent = {
        xy: "←→ X / ↑↓ Y · 空白处旋转",
        xz: "←→ X / ↑↓ Z · 空白处旋转",
        yz: "←→ Z / ↑↓ Y · 空白处旋转",
      }[button.dataset.plane];
    });
  });

  root.querySelectorAll("[data-mbti]").forEach((button) => {
    button.addEventListener("click", () => {
      draft = { ...draft, mbti: button.dataset.mbti };
      renderDraft();
    });
  });

  root.querySelector(".reset-profile").addEventListener("click", () => {
    draft = { ...DEFAULT_PROFILE };
    renderDraft();
  });
  root.querySelector(".save-profile").addEventListener("click", () => {
    draft = saveProfile(window.localStorage, draft);
    appState.saveProfile(draft);
  });
  root.querySelector(".workspace-back").addEventListener("click", () => {
    appState.closeWorkspace();
  });

  renderDraft();

  return () => particleSpace.dispose();
}
