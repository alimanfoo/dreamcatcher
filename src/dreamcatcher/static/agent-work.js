"use strict";

const feed = document.querySelector(".feed-records");
const feedTail = document.querySelector(".feed-tail");
const agentWorkSidebar = document.querySelector(".agent-work-sidebar");
let shouldFollowFeed = false;
let currentRoundHash = null;
let focusedRoundHash = null;

function updateFeedTailVisibility() {
  feedTail?.toggleAttribute("hidden", shouldFollowFeed);
}

if (feed !== null) {
  feed.scrollTop = feed.scrollHeight;
  shouldFollowFeed = true;
  updateFeedTailVisibility();
  feed.addEventListener(
    "pointerdown",
    () => {
      shouldFollowFeed = false;
      updateFeedTailVisibility();
    },
    { passive: true },
  );
  feed.addEventListener(
    "wheel",
    () => {
      shouldFollowFeed = false;
      updateFeedTailVisibility();
    },
    { passive: true },
  );
  if (feedTail !== null) {
    feedTail.addEventListener("click", () => {
      shouldFollowFeed = true;
      updateFeedTailVisibility();
      feed.scrollTo({
        top: feed.scrollHeight,
        behavior: "instant",
      });
    });
  }
  feed.addEventListener("htmx:beforeSwap", (event) => {
    if (event.detail.target !== feed) {
      return;
    }
    shouldFollowFeed ||=
      feed.scrollHeight - feed.scrollTop - feed.clientHeight <= 1;
    updateFeedTailVisibility();
    const currentRoundLink = agentWorkSidebar?.querySelector(
      '.round-link[aria-current="true"]',
    );
    const focusedRoundLink = document.activeElement?.closest(".round-link");
    currentRoundHash = currentRoundLink?.hash ?? null;
    focusedRoundHash = agentWorkSidebar?.contains(focusedRoundLink)
      ? focusedRoundLink.hash
      : null;
  });
  feed.addEventListener("htmx:afterSwap", (event) => {
    if (event.detail.target !== feed) {
      return;
    }
    if (shouldFollowFeed) {
      feed.scrollTop = feed.scrollHeight;
    }
    const currentRoundLink = agentWorkSidebar?.querySelector(
      `.round-link[href="${currentRoundHash}"]`,
    );
    currentRoundLink?.setAttribute("aria-current", "true");
    const focusedRoundLink = agentWorkSidebar?.querySelector(
      `.round-link[href="${focusedRoundHash}"]`,
    );
    focusedRoundLink?.focus({ preventScroll: true });
  });
}

if (agentWorkSidebar !== null) {
  agentWorkSidebar.addEventListener("click", (event) => {
    const roundLink = event.target.closest(".round-link");
    if (feed === null || roundLink === null) {
      return;
    }
    const feedRound = document.querySelector(roundLink.hash);
    if (feedRound === null) {
      return;
    }
    event.preventDefault();
    shouldFollowFeed = false;
    updateFeedTailVisibility();
    for (const otherLink of agentWorkSidebar.querySelectorAll(".round-link")) {
      otherLink.removeAttribute("aria-current");
    }
    roundLink.setAttribute("aria-current", "true");
    const feedTop = feed.getBoundingClientRect().top;
    const roundTop = feedRound.getBoundingClientRect().top;
    feed.scrollTo({
      top: feed.scrollTop + roundTop - feedTop,
      behavior: "smooth",
    });
  });
}

// The tail replaces the controls on every poll, so the listener sits above them.
document.addEventListener("submit", (event) => {
  const form = event.target;
  if (
    form.dataset.confirmation !== undefined &&
    !window.confirm(form.dataset.confirmation)
  ) {
    event.preventDefault();
  }
});
