import { createParticles } from "../lib/particles.js";
import { createIdleScheduler } from "../lib/idle-scheduler.js";

const TAU = Math.PI * 2;

export class ParticleField {
  constructor(canvas) {
    this.canvas = canvas;
    this.context = canvas.getContext("2d", { alpha: true });
    this.pointer = { x: 0, y: 0 };
    this.targetPointer = { x: 0, y: 0 };
    this.reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    this.scheduler = createIdleScheduler({
      duration: 820,
      render: (time) => this.render(time),
    });
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(canvas);
    this.handleVisibility = () => {
      if (document.hidden) {
        this.scheduler.stop();
      } else {
        this.scheduler.renderOnce(performance.now());
      }
    };
    document.addEventListener("visibilitychange", this.handleVisibility);
    this.resize();
  }

  resize() {
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const bounds = this.canvas.getBoundingClientRect();
    this.width = Math.max(1, bounds.width);
    this.height = Math.max(1, bounds.height);
    this.canvas.width = Math.round(this.width * ratio);
    this.canvas.height = Math.round(this.height * ratio);
    this.context.setTransform(ratio, 0, 0, ratio, 0, 0);
    this.particles = createParticles({
      count: Math.min(140, Math.round((this.width * this.height) / 14000)),
      width: this.width,
      height: this.height,
      seed: 20260725,
    });
    this.scheduler.renderOnce(performance.now());
  }

  setPointer(x, y) {
    this.targetPointer.x = x;
    this.targetPointer.y = y;
    if (this.reducedMotion) {
      this.pointer.x = x;
      this.pointer.y = y;
      this.scheduler.renderOnce(performance.now());
      return;
    }
    this.scheduler.wake(performance.now());
  }

  drawGrid(time) {
    const { context, width, height, pointer } = this;
    const horizon = height * 0.69 + pointer.y * 10;
    const vanishingX = width * 0.68 + pointer.x * 34;

    context.save();
    context.globalCompositeOperation = "screen";
    context.lineWidth = 0.65;

    for (let index = -12; index <= 12; index += 1) {
      const baseX = vanishingX + index * 92;
      const gradient = context.createLinearGradient(vanishingX, horizon, baseX, height);
      gradient.addColorStop(0, "rgba(225, 230, 235, 0)");
      gradient.addColorStop(0.45, "rgba(225, 230, 235, 0.018)");
      gradient.addColorStop(1, "rgba(225, 230, 235, 0.055)");
      context.strokeStyle = gradient;
      context.beginPath();
      context.moveTo(vanishingX, horizon);
      context.lineTo(baseX, height);
      context.stroke();
    }

    for (let index = 0; index < 12; index += 1) {
      const progress = index / 11;
      const eased = progress ** 2.15;
      const y = horizon + eased * (height - horizon);
      context.strokeStyle = `rgba(219, 224, 229, ${0.012 + eased * 0.04})`;
      context.beginPath();
      context.moveTo(0, y);
      context.lineTo(width, y);
      context.stroke();
    }

    const scan = (time * 0.035) % Math.max(height, 1);
    const scanGradient = context.createLinearGradient(0, scan - 50, 0, scan + 50);
    scanGradient.addColorStop(0, "rgba(255, 255, 255, 0)");
    scanGradient.addColorStop(0.5, "rgba(255, 255, 255, 0.018)");
    scanGradient.addColorStop(1, "rgba(255, 255, 255, 0)");
    context.fillStyle = scanGradient;
    context.fillRect(0, scan - 50, width, 100);
    context.restore();
  }

  drawParticles(time) {
    const { context, width, height, particles, pointer } = this;

    for (const particle of particles) {
      const speed = particle.kind === "ember" ? 0.007 : 0.0025;
      const wave = Math.sin(time * speed + particle.phase);
      const x =
        (particle.x + time * particle.drift * particle.depth + pointer.x * particle.depth * 10 + width) %
        width;
      const y = (particle.y + wave * 7 * particle.depth + height) % height;
      const radius = particle.kind === "axis" ? 1.15 : 0.35 + particle.depth * 0.75;

      context.beginPath();
      context.fillStyle =
        particle.kind === "ember"
          ? `rgba(255, 255, 255, ${0.035 + particle.depth * 0.1})`
          : `rgba(205, 212, 219, ${0.035 + particle.depth * 0.14})`;
      context.arc(x, y, radius, 0, TAU);
      context.fill();

      if (particle.kind === "axis") {
        context.strokeStyle = `rgba(224, 229, 234, ${0.018 + particle.depth * 0.04})`;
        context.lineWidth = 0.5;
        context.beginPath();
        context.moveTo(x - 24 * particle.depth, y);
        context.lineTo(x + 34 * particle.depth, y);
        context.moveTo(x, y - 14 * particle.depth);
        context.lineTo(x, y + 22 * particle.depth);
        context.stroke();
      }
    }
  }

  render(time) {
    this.pointer.x += (this.targetPointer.x - this.pointer.x) * 0.045;
    this.pointer.y += (this.targetPointer.y - this.pointer.y) * 0.045;
    this.context.clearRect(0, 0, this.width, this.height);
    this.drawGrid(time);
    this.drawParticles(time);
  }

  destroy() {
    this.scheduler.stop();
    this.resizeObserver.disconnect();
    document.removeEventListener("visibilitychange", this.handleVisibility);
  }
}
