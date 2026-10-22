"use strict";

const outputAnimations = new Set();
let shouldRestoreTabFocus = false;

function activateWorkTab(tab, shouldFocus = false) {
  const tablist = tab.closest('[role="tablist"]');
  for (const candidate of tablist.querySelectorAll('[role="tab"]')) {
    const isSelected = candidate === tab;
    candidate.setAttribute("aria-selected", String(isSelected));
    candidate.tabIndex = isSelected ? 0 : -1;
    const panel = candidate.ownerDocument.getElementById(
      candidate.getAttribute("aria-controls"),
    );
    panel.toggleAttribute("hidden", !isSelected);
  }
  if (shouldFocus) {
    tab.focus();
  }
}

// The address's fragment names the selected tab, so every selection is a
// history entry. A fragment that names no tab selects the first.
function activateAddressedWorkTab(shouldFocus = false) {
  const tabs = [...document.querySelectorAll('#home [role="tab"]')];
  const tab =
    tabs.find((candidate) => candidate.hash === window.location.hash) ??
    tabs[0];
  if (tab !== undefined) {
    activateWorkTab(tab, shouldFocus);
  }
}

activateAddressedWorkTab();
window.addEventListener("hashchange", () => activateAddressedWorkTab());

document.body.addEventListener("keydown", (event) => {
  // A held modifier leaves the key to the browser, as Alt+ArrowLeft goes back.
  if (
    !(event.target instanceof Element) ||
    event.altKey ||
    event.ctrlKey ||
    event.metaKey ||
    event.shiftKey
  ) {
    return;
  }
  const tab = event.target.closest('#home [role="tab"]');
  if (tab === null) {
    return;
  }
  const tablist = tab.closest('[role="tablist"]');
  const tabs = [...tablist.querySelectorAll('[role="tab"]')];
  const currentIndex = tabs.indexOf(tab);
  let nextIndex;
  if (event.key === "ArrowRight") {
    nextIndex = (currentIndex + 1) % tabs.length;
  } else if (event.key === "ArrowLeft") {
    nextIndex = (currentIndex - 1 + tabs.length) % tabs.length;
  } else if (event.key === "Home") {
    nextIndex = 0;
  } else if (event.key === "End") {
    nextIndex = tabs.length - 1;
  } else {
    return;
  }
  event.preventDefault();
  tabs[nextIndex].focus();
  window.location.hash = tabs[nextIndex].hash;
});

function latestOutputsByWork(home) {
  const outputs = new Map();
  for (const card of home.querySelectorAll(".agent-work-card")) {
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
  shouldRestoreTabFocus =
    currentHome.querySelector('[role="tab"]:focus') !== null;
  const currentOutputs = latestOutputsByWork(currentHome);
  const updatedOutputs = latestOutputsByWork(updatedHome);
  const workIdentifiers = new Set([
    ...currentOutputs.keys(),
    ...updatedOutputs.keys(),
  ]);
  for (const identifier of workIdentifiers) {
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
  activateAddressedWorkTab(shouldRestoreTabFocus);
  shouldRestoreTabFocus = false;
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
