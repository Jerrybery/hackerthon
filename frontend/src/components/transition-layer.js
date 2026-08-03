export function getTransitionTiming(duration = 600) {
  const endAt = Math.max(200, Math.round(duration));
  return {
    swapAt: Math.round(endAt * 0.45),
    endAt,
  };
}

export function runViewTransition({
  root,
  render,
  duration = 600,
}) {
  const timing = getTransitionTiming(duration);
  const layer = document.createElement("div");
  layer.className = "view-transition-layer";
  layer.setAttribute("aria-hidden", "true");
  layer.innerHTML = "<i></i><i></i><i></i><span>PERSONA LINK / TRANSFER</span>";
  document.body.append(layer);
  root.classList.add("is-view-transitioning");

  return new Promise((resolve) => {
    window.setTimeout(() => {
      render();
      layer.classList.add("is-swapped");
    }, timing.swapAt);

    window.setTimeout(() => {
      root.classList.remove("is-view-transitioning");
      layer.remove();
      resolve();
    }, timing.endAt);
  });
}
