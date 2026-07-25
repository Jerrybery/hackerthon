import test from "node:test";
import assert from "node:assert/strict";

import { createChatSession } from "../src/lib/chat-session.js";

test("ignores empty messages", async () => {
  const session = createChatSession({
    personaId: "winter",
    agentAdapter: { reply: async () => "ok" },
  });

  await session.send("   ");

  assert.equal(session.getMessages().length, 0);
});

test("appends user and assistant messages in order", async () => {
  const session = createChatSession({
    personaId: "jarvis",
    agentAdapter: { reply: async () => "系统已就绪。" },
  });

  await session.send("状态？");

  assert.deepEqual(
    session.getMessages().map(({ role }) => role),
    ["user", "assistant"],
  );
  assert.equal(session.getMessages()[1].content, "系统已就绪。");
});

test("exposes generating state while waiting for the adapter", async () => {
  let resolveReply;
  const session = createChatSession({
    personaId: "johnny",
    agentAdapter: {
      reply: () => new Promise((resolve) => { resolveReply = resolve; }),
    },
  });

  const pending = session.send("在吗？");
  assert.equal(session.getState().generating, true);

  resolveReply("一直都在。");
  await pending;

  assert.equal(session.getState().generating, false);
});

test("records an inline error when the adapter fails", async () => {
  const session = createChatSession({
    personaId: "custom",
    agentAdapter: {
      reply: async () => { throw new Error("offline"); },
    },
  });

  await session.send("测试");

  assert.equal(session.getState().generating, false);
  assert.equal(session.getState().error, "对话通道暂时不可用，请重试。");
});
