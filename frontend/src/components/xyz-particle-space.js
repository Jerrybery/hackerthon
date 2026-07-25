import * as THREE from "three";

import {
  getParticleBudget,
  getPerformanceTier,
} from "../lib/performance-tier.js";
import { normalizeAxis } from "../lib/persona-profile.js";
import {
  applyPlaneDrag,
  axisToPosition,
  createSpherePoints,
  getDepthCompensatedScale,
} from "../lib/xyz-geometry.js";

const AXIS_COLORS = {
  x: 0xf4f7fb,
  y: 0x9ed8ff,
  z: 0xd1b3ff,
};

function createDigitTexture() {
  const canvas = document.createElement("canvas");
  canvas.width = 64;
  canvas.height = 64;
  const context = canvas.getContext("2d");
  context.clearRect(0, 0, 64, 64);
  context.fillStyle = "rgba(255,255,255,.92)";
  context.font = "700 34px ui-monospace, SFMono-Regular, Menlo, monospace";
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText("01", 32, 32);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function createAxis(axis, color) {
  const vector = {
    x: new THREE.Vector3(1.65, 0, 0),
    y: new THREE.Vector3(0, 1.65, 0),
    z: new THREE.Vector3(0, 0, 1.65),
  }[axis];
  const geometry = new THREE.BufferGeometry().setFromPoints([
    vector.clone().multiplyScalar(-1),
    vector,
  ]);
  const material = new THREE.LineBasicMaterial({
    color,
    transparent: true,
    opacity: 0.72,
  });
  return new THREE.Line(geometry, material);
}

export class XYZParticleSpace {
  constructor(container, profile) {
    this.container = container;
    this.profile = { ...profile };
    this.activePlane = "xy";
    this.onProfileChange = () => {};
    this.pointer = new THREE.Vector2();
    this.raycaster = new THREE.Raycaster();
    this.dragMode = null;
    this.lastPointer = { x: 0, y: 0 };
    this.dragStartPointer = { x: 0, y: 0 };
    this.dragStartProfile = { ...this.profile };
    this.rotationVelocity = { x: 0, y: 0 };
    this.running = false;
    this.frame = null;
    this.lastRender = 0;

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
    this.camera.position.set(0, 0.15, 4.65);

    this.renderer = new THREE.WebGLRenderer({
      alpha: true,
      antialias: false,
      powerPreference: "high-performance",
    });
    this.renderer.setClearColor(0x000000, 0);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    this.renderer.domElement.className = "xyz-webgl";
    this.renderer.domElement.setAttribute("aria-label", "XYZ 粒子人格空间");
    container.append(this.renderer.domElement);

    const tier = getPerformanceTier({
      hardwareConcurrency: navigator.hardwareConcurrency,
      dpr: window.devicePixelRatio,
    });
    const positions = createSpherePoints({
      count: getParticleBudget(tier),
      seed: 20260725,
    });
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    this.digitTexture = createDigitTexture();
    const material = new THREE.PointsMaterial({
      color: 0xe9f3fb,
      map: this.digitTexture,
      alphaMap: this.digitTexture,
      size: tier === "high" ? 0.078 : 0.086,
      sizeAttenuation: true,
      transparent: true,
      opacity: 0.94,
      alphaTest: 0.08,
      depthTest: false,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });

    this.spaceGroup = new THREE.Group();
    this.particleSphere = new THREE.Points(geometry, material);
    this.spaceGroup.add(this.particleSphere);
    this.axes = {
      x: createAxis("x", AXIS_COLORS.x),
      y: createAxis("y", AXIS_COLORS.y),
      z: createAxis("z", AXIS_COLORS.z),
    };
    Object.values(this.axes).forEach((line) => this.spaceGroup.add(line));

    const originGeometry = new THREE.SphereGeometry(0.028, 12, 12);
    const originMaterial = new THREE.MeshBasicMaterial({
      color: 0xffffff,
      transparent: true,
      opacity: 0.7,
    });
    this.origin = new THREE.Mesh(originGeometry, originMaterial);
    this.spaceGroup.add(this.origin);

    const pointGeometry = new THREE.SphereGeometry(0.095, 24, 24);
    const pointMaterial = new THREE.MeshBasicMaterial({
      color: 0xffffff,
      transparent: true,
      opacity: 0.95,
    });
    this.personaPoint = new THREE.Mesh(pointGeometry, pointMaterial);
    const glowMaterial = new THREE.MeshBasicMaterial({
      color: 0xa7ddff,
      transparent: true,
      opacity: 0.18,
      side: THREE.BackSide,
    });
    this.pointGlow = new THREE.Mesh(
      new THREE.SphereGeometry(0.18, 20, 20),
      glowMaterial,
    );
    this.depthOrbit = new THREE.Mesh(
      new THREE.TorusGeometry(0.16, 0.006, 8, 56),
      new THREE.MeshBasicMaterial({
        color: 0xdcecf6,
        transparent: true,
        opacity: 0.28,
        depthTest: false,
      }),
    );
    this.depthOrbit.rotation.x = Math.PI / 2;
    this.personaPoint.add(this.pointGlow);
    this.personaPoint.add(this.depthOrbit);
    this.spaceGroup.add(this.personaPoint);
    this.scene.add(this.spaceGroup);

    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(container);
    this.handlePointerDown = (event) => this.pointerDown(event);
    this.handlePointerMove = (event) => this.pointerMove(event);
    this.handlePointerUp = () => { this.dragMode = null; };
    this.handleVisibility = () => {
      if (document.hidden) this.stop();
      else this.start();
    };
    this.renderer.domElement.addEventListener("pointerdown", this.handlePointerDown);
    window.addEventListener("pointermove", this.handlePointerMove, { passive: false });
    window.addEventListener("pointerup", this.handlePointerUp);
    document.addEventListener("visibilitychange", this.handleVisibility);

    this.setProfile(profile);
    this.resize();
    this.start();
  }

  setOnProfileChange(callback) {
    this.onProfileChange = callback;
  }

  setActivePlane(plane) {
    if (["xy", "xz", "yz"].includes(plane)) this.activePlane = plane;
  }

  setProfile(profile) {
    this.profile = {
      ...this.profile,
      x: normalizeAxis(profile.x),
      y: normalizeAxis(profile.y),
      z: normalizeAxis(profile.z),
    };
    const position = axisToPosition(this.profile);
    this.personaPoint.position.set(position.x, position.y, position.z);
    this.personaPoint.scale.setScalar(getDepthCompensatedScale({
      z: position.z,
      cameraZ: this.camera.position.z,
    }));
    this.depthOrbit.material.opacity = 0.16 + ((position.z + 1) / 2) * 0.34;
    this.depthOrbit.rotation.z = position.z * Math.PI * 0.5;
    this.updateAxisLight();
  }

  updateAxisLight() {
    for (const axis of ["x", "y", "z"]) {
      const strength = Math.abs(this.profile[axis]) / 100;
      this.axes[axis].material.opacity = 0.34 + strength * 0.66;
    }
  }

  updatePointer(event) {
    const bounds = this.renderer.domElement.getBoundingClientRect();
    this.pointer.x = ((event.clientX - bounds.left) / bounds.width) * 2 - 1;
    this.pointer.y = -((event.clientY - bounds.top) / bounds.height) * 2 + 1;
    this.raycaster.setFromCamera(this.pointer, this.camera);
  }

  pointerDown(event) {
    this.updatePointer(event);
    const hits = this.raycaster.intersectObject(this.personaPoint, true);
    this.lastPointer = { x: event.clientX, y: event.clientY };
    if (hits.length) {
      this.dragMode = "point";
      this.dragStartPointer = { x: event.clientX, y: event.clientY };
      this.dragStartProfile = { ...this.profile };
    } else {
      this.dragMode = "rotate";
    }
    this.renderer.domElement.setPointerCapture?.(event.pointerId);
  }

  pointerMove(event) {
    if (!this.dragMode) return;
    event.preventDefault();
    if (this.dragMode === "rotate") {
      const deltaX = event.clientX - this.lastPointer.x;
      const deltaY = event.clientY - this.lastPointer.y;
      this.spaceGroup.rotation.y += deltaX * 0.006;
      this.spaceGroup.rotation.x += deltaY * 0.004;
      this.rotationVelocity = { x: deltaY * 0.0009, y: deltaX * 0.0012 };
      this.lastPointer = { x: event.clientX, y: event.clientY };
      return;
    }

    const bounds = this.renderer.domElement.getBoundingClientRect();
    const next = applyPlaneDrag(this.dragStartProfile, {
      plane: this.activePlane,
      deltaX: event.clientX - this.dragStartPointer.x,
      deltaY: event.clientY - this.dragStartPointer.y,
      width: bounds.width,
      height: bounds.height,
    });
    this.setProfile(next);
    this.onProfileChange({ ...this.profile });
  }

  resize() {
    const bounds = this.container.getBoundingClientRect();
    const width = Math.max(1, bounds.width);
    const height = Math.max(1, bounds.height);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height, false);
    this.render(performance.now());
  }

  render(time) {
    const pulse = 1 + Math.sin(time * 0.002) * 0.08;
    this.pointGlow.scale.setScalar(pulse);
    this.spaceGroup.rotation.x += this.rotationVelocity.x;
    this.spaceGroup.rotation.y += this.rotationVelocity.y;
    this.rotationVelocity.x *= 0.94;
    this.rotationVelocity.y *= 0.94;
    this.renderer.render(this.scene, this.camera);
  }

  animate = (time) => {
    if (!this.running) return;
    if (time - this.lastRender >= 32) {
      this.lastRender = time;
      this.render(time);
    }
    this.frame = requestAnimationFrame(this.animate);
  };

  start() {
    if (this.running) return;
    this.running = true;
    this.frame = requestAnimationFrame(this.animate);
  }

  stop() {
    this.running = false;
    if (this.frame !== null) cancelAnimationFrame(this.frame);
    this.frame = null;
  }

  dispose() {
    this.stop();
    this.resizeObserver.disconnect();
    this.renderer.domElement.removeEventListener("pointerdown", this.handlePointerDown);
    window.removeEventListener("pointermove", this.handlePointerMove);
    window.removeEventListener("pointerup", this.handlePointerUp);
    document.removeEventListener("visibilitychange", this.handleVisibility);
    this.scene.traverse((object) => {
      object.geometry?.dispose?.();
      if (Array.isArray(object.material)) {
        object.material.forEach((material) => material.dispose?.());
      } else {
        object.material?.dispose?.();
      }
    });
    this.digitTexture.dispose();
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}
