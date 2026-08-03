const RESPONSES = {
  winter: [
    "收到。我会先判断风险，再给你最短的行动路线。",
    "环境稳定。把目标说清楚，剩下的交给我。",
  ],
  johnny: [
    "规矩不是答案。你先说想打破哪一条。",
    "听见了。别给我漂亮话，给我真正的问题。",
  ],
  jarvis: [
    "系统已就绪。我会为你整理信息，并保留必要的判断依据。",
    "当然。建议先确定优先级，然后逐项处理。",
  ],
  custom: [
    "我正在按照你设定的人格坐标回应。告诉我，此刻你最想讨论什么？",
    "人格参数已同步。我们可以从一个具体问题开始。",
  ],
};

export function createMockAgentAdapter({
  delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds)),
} = {}) {
  let responseIndex = 0;

  return {
    async reply({ personaId }) {
      await delay(620);
      const options = RESPONSES[personaId] ?? RESPONSES.custom;
      const response = options[responseIndex % options.length];
      responseIndex += 1;
      return response;
    },
  };
}
