"use strict";

const feed = document.querySelector(".feed-records");
const feedTail = document.querySelector(".feed-tail");
const agentWorkSidebar = document.querySelector(".agent-work-sidebar");
let shouldFollowFeed = false;
let currentRoundHash = null;
let focusedRoundHash = null;

function isFeedAtEnd() {
  return feed.scrollHeight - feed.scrollTop - feed.clientHeight <= 1;
}

// The feed animates scrolls, and each frame of one fires a scroll event short
// of the end, so the page's own scrolls to the end are instant.
function scrollFeedToEnd() {
  feed.scrollTo({ top: feed.scrollHeight, behavior: "instant" });
}

function updateFeedTailVisibility() {
  feedTail?.toggleAttribute("hidden", shouldFollowFeed);
}

if (feed !== null) {
  scrollFeedToEnd();
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
    "scroll",
    () => {
      shouldFollowFeed = isFeedAtEnd();
      updateFeedTailVisibility();
    },
    { passive: true },
  );
  if (feedTail !== null) {
    feedTail.addEventListener("click", () => {
      shouldFollowFeed = true;
      updateFeedTailVisibility();
      scrollFeedToEnd();
    });
  }
  feed.addEventListener("htmx:beforeSwap", (event) => {
    if (event.detail.target !== feed) {
      return;
    }
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
      scrollFeedToEnd();
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
