"use strict";

// The fixed working-motif layer begins where the site header actually ends.
// The home-page refresh morphs the header in place, so this observer continues
// to follow changes from wrapping, fonts and refreshed content.
const siteHeader = document.querySelector(".site-header");
const setSiteHeaderHeight = () => {
  document.documentElement.style.setProperty(
    "--site-header-height",
    `${siteHeader.getBoundingClientRect().height}px`,
  );
};
setSiteHeaderHeight();
new ResizeObserver(setSiteHeaderHeight).observe(siteHeader);

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

document.body.addEventListener("htmx:beforeSwap", (event) => {
  if (event.detail.target.id !== "home") {
    return;
  }
  shouldRestoreTabFocus =
    event.detail.target.querySelector('[role="tab"]:focus') !== null;
});

document.body.addEventListener("htmx:afterSwap", (event) => {
  if (event.detail.target.id !== "home") {
    return;
  }
  activateAddressedWorkTab(shouldRestoreTabFocus);
  shouldRestoreTabFocus = false;
});
