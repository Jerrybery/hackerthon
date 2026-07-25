export function createChatSession({
  personaId,
  agentAdapter,
  initialMessages = [],
}) {
  let sequence = initialMessages.length;
  let state = {
    messages: initialMessages.map((message) => ({ ...message })),
    generating: false,
    error: null,
  };
  const listeners = new Set();

  function emit() {
    const snapshot = {
      ...state,
      messages: state.messages.map((message) => ({ ...message })),
    };
    listeners.forEach((listener) => listener(snapshot));
  }

  function append(role, content, status = "complete") {
    sequence += 1;
    const message = {
      id: `${personaId}-${sequence}`,
      role,
      content,
      status,
      createdAt: Date.now(),
    };
    state = { ...state, messages: [...state.messages, message] };
    return message;
  }

  return {
    getMessages() {
      return state.messages.map((message) => ({ ...message }));
    },
    getState() {
      return {
        ...state,
        messages: state.messages.map((message) => ({ ...message })),
      };
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    async send(value) {
      const content = String(value ?? "").trim();
      if (!content || state.generating) return false;

      append("user", content);
      state = { ...state, generating: true, error: null };
      emit();

      try {
        const reply = await agentAdapter.reply({
          personaId,
          messages: state.messages.map((message) => ({ ...message })),
        });
        append("assistant", String(reply));
        state = { ...state, generating: false };
      } catch {
        state = {
          ...state,
          generating: false,
          error: "对话通道暂时不可用，请重试。",
        };
      }

      emit();
      return !state.error;
    },
  };
}
