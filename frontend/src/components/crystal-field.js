import { createCrystalShards } from "../lib/crystal-shards.js";

export class CrystalField {
  constructor(canvas) {
    this.canvas = canvas;
    this.context = canvas.getContext("2d", { alpha: true });
    this.pointer = { x: 0, y: 0 };
    this.targetPointer = { x: 0, y: 0 };
    this.reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(canvas);
    this.resize();
    this.animate = this.animate.bind(this);
    this.frame = requestAnimationFrame(this.animate);
  }

  resize() {
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const bounds = this.canvas.getBoundingClientRect();
    this.width = Math.max(1, bounds.width);
    this.height = Math.max(1, bounds.height);
    this.canvas.width = Math.round(this.width * ratio);
    this.canvas.height = Math.round(this.height * ratio);
    this.context.setTransform(ratio, 0, 0, ratio, 0, 0);
    this.shards = createCrystalShards({
      count: this.width < 1200 ? 28 : 36,
      seed: 20260725,
    });
  }

  setPointer(x, y) {
    this.targetPointer.x = Math.max(-0.5, Math.min(0.5, x));
    this.targetPointer.y = Math.max(-0.5, Math.min(0.5, y));
  }

  drawHorizon() {
    const { context, width, height, pointer } = this;
    const x = width * (0.6 + pointer.x * 0.025);
    const y = height * (0.73 + pointer.y * 0.012);
    const radius = width * 0.36;
    const glow = context.createRadialGradient(x, y, 0, x, y, radius);
    glow.addColorStop(0, "rgba(205, 236, 255, 0.22)");
    glow.addColorStop(0.18, "rgba(118, 190, 230, 0.09)");
    glow.addColorStop(0.52, "rgba(45, 93, 125, 0.035)");
    glow.addColorStop(1, "rgba(0, 0, 0, 0)");
    context.fillStyle = glow;
    context.fillRect(x - radius, y - radius, radius * 2, radius * 2);
  }

  drawShard(shard, index, time) {
    const { context, width, height, pointer } = this;
    const depthScale = 0.62 + shard.depth * 0.24;
    const direction = index % 4 === 0 ? -1 : 1;
    const travel = time * shard.speed * direction;
    const normalizedY = ((shard.y + travel) % 1 + 1) % 1;
    const pulse = Math.sin(time * 0.00045 * (1 + shard.depth * 0.18) + shard.phase);
    const parallax = (0.45 + shard.depth * 0.28) * 18;
    const x = shard.x * width + pointer.x * parallax;
    const y = normalizedY * height + pointer.y * parallax * 0.55;
    const shardWidth = Math.max(2, width * shard.width * depthScale * (0.32 + Math.abs(pulse) * 0.68));
    const shardHeight = height * shard.height * depthScale;
    const opacity = shard.opacity * (0.68 + shard.depth * 0.18);
    const gradient = context.createLinearGradient(-shardWidth / 2, 0, shardWidth / 2, 0);

    gradient.addColorStop(0, `rgba(36, 64, 84, ${opacity * 0.3})`);
    gradient.addColorStop(0.22, `rgba(168, 216, 242, ${opacity * 0.72})`);
    gradient.addColorStop(0.48, `rgba(239, 249, 255, ${opacity})`);
    gradient.addColorStop(0.58, `rgba(78, 135, 168, ${opacity * 0.7})`);
    gradient.addColorStop(1, `rgba(9, 20, 30, ${opacity * 0.15})`);

    context.save();
    context.translate(x, y);
    context.rotate(shard.tilt + pulse * 0.035);
    context.filter = `blur(${shard.blur}px)`;
    context.fillStyle = gradient;
    context.shadowColor = "rgba(151, 220, 255, 0.28)";
    context.shadowBlur = shard.depth === 2 ? 14 : 5;
    context.fillRect(-shardWidth / 2, -shardHeight / 2, shardWidth, shardHeight);

    context.filter = "none";
    context.lineWidth = 0.55;
    context.strokeStyle = `rgba(225, 246, 255, ${opacity * 1.45})`;
    context.strokeRect(-shardWidth / 2, -shardHeight / 2, shardWidth, shardHeight);

    if (shard.depth > 0 && shardWidth > 8) {
      context.strokeStyle = `rgba(219, 242, 255, ${opacity * 0.72})`;
      context.beginPath();
      context.moveTo(-shardWidth * 0.38, -shardHeight * 0.24);
      context.lineTo(shardWidth * 0.08, -shardHeight * 0.02);
      context.lineTo(-shardWidth * 0.18, shardHeight * 0.31);
      context.moveTo(shardWidth * 0.1, -shardHeight * 0.02);
      context.lineTo(shardWidth * 0.36, shardHeight * 0.14);
      context.stroke();
    }

    context.restore();
  }

  drawReflections(time) {
    const { context, width, height } = this;
    const horizon = height * 0.73;
    const reflection = context.createLinearGradient(0, horizon, 0, height);
    reflection.addColorStop(0, "rgba(135, 211, 252, 0.055)");
    reflection.addColorStop(0.28, "rgba(81, 148, 189, 0.026)");
    reflection.addColorStop(1, "rgba(0, 0, 0, 0)");
    context.fillStyle = reflection;
    context.fillRect(0, horizon, width, height - horizon);

    for (let index = 0; index < 11; index += 1) {
      const progress = index / 10;
      const y = horizon + progress ** 1.65 * (height - horizon);
      const shift = Math.sin(time * 0.00034 + index) * width * 0.025;
      context.strokeStyle = `rgba(184, 226, 249, ${0.018 + progress * 0.026})`;
      context.lineWidth = 0.6;
      context.beginPath();
      context.moveTo(width * 0.21 + shift, y);
      context.bezierCurveTo(
        width * 0.38,
        y - 2.5,
        width * 0.61,
        y + 2.5,
        width * 0.87 + shift,
        y,
      );
      context.stroke();
    }
  }

  render(time = 0) {
    this.context.clearRect(0, 0, this.width, this.height);
    this.context.globalCompositeOperation = "screen";
    this.drawHorizon();
    this.shards.forEach((shard, index) => this.drawShard(shard, index, time));
    this.drawReflections(time);
    this.context.globalCompositeOperation = "source-over";
  }

  animate(time) {
    this.pointer.x += (this.targetPointer.x - this.pointer.x) * 0.035;
    this.pointer.y += (this.targetPointer.y - this.pointer.y) * 0.035;
    this.render(time);

    if (!this.reducedMotion) {
      this.frame = requestAnimationFrame(this.animate);
    }
  }

  destroy() {
    cancelAnimationFrame(this.frame);
    this.resizeObserver.disconnect();
  }
}
