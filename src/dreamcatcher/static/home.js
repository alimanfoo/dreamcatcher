"use strict";

const outputAnimations = new Set();

function latestOutputsByAssignment(home) {
  const outputs = new Map();
  for (const card of home.querySelectorAll(".assignment-card")) {
    outputs.set(card.id, card.querySelector(".latest-output"));
  }
  return outputs;
}

document.body.addEventListener("htmx:beforeSwap", (event) => {
  if (event.detail.target.id !== "home") {
    return;
  }
  const currentHome = document.querySelector("#home");
  const updatedHome = new DOMParser()
    .parseFromString(event.detail.serverResponse, "text/html")
    .querySelector("#home");
  if (currentHome === null || updatedHome === null) {
    return;
  }
  const currentOutputs = latestOutputsByAssignment(currentHome);
  const updatedOutputs = latestOutputsByAssignment(updatedHome);
  const assignmentIdentifiers = new Set([
    ...currentOutputs.keys(),
    ...updatedOutputs.keys(),
  ]);
  for (const identifier of assignmentIdentifiers) {
    const currentOutput = currentOutputs.get(identifier) ?? null;
    const updatedOutput = updatedOutputs.get(identifier) ?? null;
    if (currentOutput?.textContent === updatedOutput?.textContent) {
      continue;
    }
    outputAnimations.add(identifier);
    currentOutput?.classList.add("is-replacing");
  }
});

document.body.addEventListener("htmx:afterSwap", (event) => {
  if (event.detail.target.id !== "home") {
    return;
  }
  const prefersReducedMotion = window.matchMedia(
    "(prefers-reduced-motion: reduce)",
  ).matches;
  for (const identifier of outputAnimations) {
    outputAnimations.delete(identifier);
    const output = document
      .getElementById(identifier)
      ?.querySelector(".latest-output");
    if (output === null || output === undefined) {
      continue;
    }
    output.classList.remove("is-replacing");
    if (prefersReducedMotion) {
      continue;
    }
    output.classList.add("is-typing");
    output.addEventListener(
      "animationend",
      () => output.classList.remove("is-typing"),
      { once: true },
    );
  }
});

document.body.addEventListener("htmx:responseError", (event) => {
  if (event.detail.target.id !== "home") {
    return;
  }
  const message = new DOMParser()
    .parseFromString(event.detail.xhr.response, "text/html")
    .querySelector(".error-message");
  const alert = document.querySelector("#home-refresh-error");
  if (message === null || alert === null) {
    return;
  }
  alert.textContent = `Refresh failed. Showing the last successful status. ${message.textContent}`;
  alert.hidden = false;
});
