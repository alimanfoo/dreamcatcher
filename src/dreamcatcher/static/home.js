"use strict";

const outputAnimations = new Set();
let selectedTabId = null;
let shouldRestoreTabFocus = false;

function activateWorkTab(tab, shouldFocus = false) {
  const tablist = tab.closest('[role="tablist"]');
  if (tablist === null) {
    return;
  }
  for (const candidate of tablist.querySelectorAll('[role="tab"]')) {
    const isSelected = candidate === tab;
    candidate.setAttribute("aria-selected", String(isSelected));
    candidate.tabIndex = isSelected ? 0 : -1;
    const panel = candidate.ownerDocument.getElementById(
      candidate.getAttribute("aria-controls"),
    );
    panel?.toggleAttribute("hidden", !isSelected);
  }
  if (shouldFocus) {
    tab.focus();
  }
}

const initialTab = document.querySelector(
  '#home [role="tab"][aria-selected="true"]',
);
if (initialTab !== null) {
  activateWorkTab(initialTab);
}

document.body.addEventListener("click", (event) => {
  if (!(event.target instanceof Element)) {
    return;
  }
  const tab = event.target.closest('#home [role="tab"]');
  if (tab !== null) {
    activateWorkTab(tab);
  }
});

document.body.addEventListener("keydown", (event) => {
  if (!(event.target instanceof Element)) {
    return;
  }
  const tab = event.target.closest('#home [role="tab"]');
  if (tab === null) {
    return;
  }
  const tablist = tab.closest('[role="tablist"]');
  if (tablist === null) {
    return;
  }
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
  activateWorkTab(tabs[nextIndex], true);
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
  selectedTabId =
    currentHome.querySelector('[role="tab"][aria-selected="true"]')?.id ?? null;
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
  const home = event.detail.target;
  const tabs = [...home.querySelectorAll('[role="tab"]')];
  const selectedTab = tabs.find((tab) => tab.id === selectedTabId) ?? tabs[0];
  const shouldFocus = shouldRestoreTabFocus;
  selectedTabId = null;
  shouldRestoreTabFocus = false;
  if (selectedTab !== undefined) {
    activateWorkTab(selectedTab, shouldFocus);
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
