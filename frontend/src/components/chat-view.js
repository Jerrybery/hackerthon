import { createMockAgentAdapter } from "../adapters/mock-agent-adapter.js";
import { createMockMediaAdapter } from "../adapters/mock-media-adapter.js";
import { createChatSession } from "../lib/chat-session.js";
import { describeProfile } from "../lib/persona-profile.js";
import { getPersona } from "../lib/personas.js";

const sessions = new Map();
const agentAdapter = createMockAgentAdapter();

const VISION_STATES = [
  { key: "searching", label: "未检测到用户", detail: "VISION SEARCHING" },
  { key: "detected", label: "已检测到用户", detail: "PRESENCE DETECTED" },
  { key: "greeted", label: "已完成问候", detail: "GREETING COMPLETE" },
];

const PROMPT_DECK = [
  { index: "01", label: "读取当前人格状态", prompt: "读取我当前的人格坐标，并告诉我它会怎样影响你的回应。" },
  { index: "02", label: "开始一次深度对话", prompt: "我们开始一次不回避真实想法的对话。" },
  { index: "03", label: "生成今日意识简报", prompt: "根据当前人格状态，为我生成一份简短的今日意识简报。" },
];

function getSession(persona) {
  if (sessions.has(persona.id)) return sessions.get(persona.id);
  const session = createChatSession({
    personaId: persona.id,
    agentAdapter,
    initialMessages: [{
      id: `${persona.id}-welcome`,
      role: "assistant",
      content: {
        winter: "连接稳定。说吧，你需要我处理什么？",
        johnny: "信号接通了。别浪费时间，说点真的。",
        jarvis: "晚上好。系统在线，我已准备好协助你。",
        custom: "人格坐标已经加载。我们从哪里开始？",
      }[persona.id],
      status: "complete",
      createdAt: Date.now(),
    }],
  });
  sessions.set(persona.id, session);
  return session;
}

function formatTime(timestamp) {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(timestamp));
}

function createMessageElement(message, persona) {
  const article = document.createElement("article");
  article.className = `chat-message chat-message--${message.role}`;
  article.dataset.messageId = message.id;

  const label = document.createElement("div");
  label.className = "chat-message__meta";
  const name = document.createElement("span");
  name.textContent = message.role === "user" ? "YOU / LOCAL" : persona.english;
  const time = document.createElement("time");
  time.dateTime = new Date(message.createdAt).toISOString();
  time.textContent = formatTime(message.createdAt);
  label.append(name, time);

  const content = document.createElement("p");
  content.textContent = message.content;
  article.append(label, content);
  return article;
}

export function mountChatView({ root, appState }) {
  const state = appState.getState();
  const persona = getPersona(state.personaId) ?? getPersona("custom");
  const session = getSession(persona);
  const mediaAdapter = createMockMediaAdapter();
  let visionIndex = 0;

  root.innerHTML = `
    <section class="chat-workspace" data-chat-persona="${persona.id}">
      <div class="chat-atmosphere" aria-hidden="true"></div>
      <div class="chat-signal-field" aria-hidden="true"><i></i><i></i><i></i><i></i></div>
      <header class="workspace-topbar chat-topbar">
        <button class="workspace-back" type="button"><span>←</span> 返回人格矩阵</button>
        <div class="workspace-brand"><b>AD·VX</b><small>CONSCIOUSNESS CHANNEL</small></div>
        <p><i></i> CHANNEL SECURE <span>03 / 04</span></p>
      </header>

      <aside class="chat-identity">
        <div class="chat-portrait">
          <img src="${persona.heroImage}" alt="${persona.name}的人格形象" />
          <i aria-hidden="true"></i>
        </div>
        <div class="chat-identity__copy">
          <small>ACTIVE CONSCIOUSNESS</small>
          <h1>${persona.name}</h1>
          <p>${persona.english}</p>
          <div><span></span>${persona.signature}</div>
        </div>
      </aside>

      <main class="chat-main">
        <header class="chat-main__heading">
          <div>
            <small>LIVE CONVERSATION / ${persona.number}</small>
            <h2>意识通道</h2>
          </div>
          <p><i></i> RESPONSE MODEL READY</p>
        </header>
        <div class="chat-thread" role="log" aria-live="polite"></div>
        <div class="chat-prompt-deck" aria-label="对话建议">
          ${PROMPT_DECK.map((item) => `
            <button type="button" data-prompt="${item.prompt}">
              <small>${item.index}</small>
              <span>${item.label}</span>
              <i>→</i>
            </button>
          `).join("")}
        </div>
        <div class="chat-generating" hidden>
          <span></span><span></span><span></span>
          <p>${persona.name} 正在组织回应</p>
        </div>
        <p class="chat-error" role="status" hidden></p>
      </main>

      <aside class="chat-side-panel">
        <section>
          <small>PERSONA PROFILE</small>
          <strong>${persona.role}</strong>
          <p>${persona.note}</p>
        </section>
        <section>
          <small>VOICE SYNTHESIS</small>
          <div class="side-status"><i></i><span>音色已就绪<b>VOICE READY</b></span></div>
        </section>
        <button class="vision-cycle" type="button">
          <small>VISION STATUS</small>
          <div class="side-status"><i></i><span>未检测到用户<b>VISION SEARCHING</b></span></div>
          <em>点击切换演示状态</em>
        </button>
        <section class="profile-vector">
          <small>CONVERSATION VECTOR</small>
          <p>${state.profile ? describeProfile(state.profile) : persona.signature}</p>
        </section>
      </aside>

      <form class="chat-composer">
        <div class="composer-field">
          <label for="chat-input">MESSAGE INPUT</label>
          <textarea id="chat-input" rows="1" placeholder="输入你想说的话…"></textarea>
          <span>ENTER 发送 · SHIFT + ENTER 换行</span>
        </div>
        <button class="mic-button" type="button" aria-label="开始录音" data-state="idle">
          <i></i>
          <span>语音<small>VOICE</small></span>
        </button>
        <button class="send-button" type="submit">
          <span>发送消息<small>TRANSMIT</small></span>
          <i>→</i>
        </button>
      </form>
    </section>
  `;

  const thread = root.querySelector(".chat-thread");
  const generating = root.querySelector(".chat-generating");
  const error = root.querySelector(".chat-error");
  const input = root.querySelector("#chat-input");
  const sendButton = root.querySelector(".send-button");
  const micButton = root.querySelector(".mic-button");
  const visionButton = root.querySelector(".vision-cycle");

  function renderSession(nextState = session.getState()) {
    thread.replaceChildren(
      ...nextState.messages.map((message) => createMessageElement(message, persona)),
    );
    generating.hidden = !nextState.generating;
    sendButton.disabled = nextState.generating;
    input.disabled = nextState.generating;
    error.hidden = !nextState.error;
    error.textContent = nextState.error ?? "";
    thread.scrollTop = thread.scrollHeight;
    root.querySelector(".chat-prompt-deck").hidden =
      nextState.messages.some((message) => message.role === "user");
  }

  async function sendMessage(value = input.value) {
    const content = String(value ?? "").trim();
    if (!content) return;
    input.value = "";
    await session.send(content);
    input.focus();
  }

  async function handleSubmit(event) {
    event.preventDefault();
    await sendMessage();
  }

  function handleInputKeydown(event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      root.querySelector(".chat-composer").requestSubmit();
    }
  }

  async function handleMicrophone() {
    const mediaState = mediaAdapter.getState();
    if (mediaState === "idle") {
      mediaAdapter.startRecording();
      return;
    }
    if (mediaState === "recording") {
      const transcript = await mediaAdapter.stopRecording();
      if (transcript) await sendMessage(transcript);
    }
  }

  function renderMediaState(nextState) {
    micButton.dataset.state = nextState;
    micButton.setAttribute(
      "aria-label",
      nextState === "recording" ? "停止录音" : "开始录音",
    );
    const label = micButton.querySelector("span");
    label.childNodes[0].textContent = {
      idle: "语音",
      recording: "录音中",
      transcribing: "转写中",
    }[nextState];
  }

  function cycleVision() {
    visionIndex = (visionIndex + 1) % VISION_STATES.length;
    const vision = VISION_STATES[visionIndex];
    visionButton.dataset.state = vision.key;
    const status = visionButton.querySelector(".side-status span");
    status.childNodes[0].textContent = vision.label;
    status.querySelector("b").textContent = vision.detail;
  }

  const unsubscribeSession = session.subscribe(renderSession);
  const unsubscribeMedia = mediaAdapter.subscribe(renderMediaState);
  root.querySelector(".chat-composer").addEventListener("submit", handleSubmit);
  input.addEventListener("keydown", handleInputKeydown);
  micButton.addEventListener("click", handleMicrophone);
  visionButton.addEventListener("click", cycleVision);
  root.querySelectorAll("[data-prompt]").forEach((button) => {
    button.addEventListener("click", () => sendMessage(button.dataset.prompt));
  });
  root.querySelector(".workspace-back").addEventListener("click", () => {
    appState.closeWorkspace();
  });

  renderSession();
  renderMediaState("idle");
  input.focus();

  return () => {
    unsubscribeSession();
    unsubscribeMedia();
  };
}
