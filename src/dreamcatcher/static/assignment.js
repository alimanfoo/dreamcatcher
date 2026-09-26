"use strict";

const feed = document.querySelector(".feed-records");
const feedTail = document.querySelector(".feed-tail");
const assignmentSidebar = document.querySelector(".assignment-sidebar");
const outputTypingDuration = Number.parseFloat(
  getComputedStyle(document.documentElement).getPropertyValue(
    "--output-typing-duration",
  ),
);
let shouldFollowFeed = false;
let feedLineCountBeforeSwap = 0;
let nextFeedLineRevealAt = 0;
let currentRoundHash = null;
let focusedRoundHash = null;

function updateFeedTailVisibility() {
  feedTail?.toggleAttribute("hidden", shouldFollowFeed);
}

function typeNewFeedLines() {
  const newFeedLines = [...feed.querySelectorAll(".feed-line")].slice(
    feedLineCountBeforeSwap,
  );
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    nextFeedLineRevealAt = performance.now();
    return;
  }
  if (newFeedLines.length === 0) {
    return;
  }
  const now = performance.now();
  const firstRevealAt = Math.max(now, nextFeedLineRevealAt);
  for (const [index, line] of newFeedLines.entries()) {
    const delay = firstRevealAt - now + index * outputTypingDuration;
    line.style.setProperty("--feed-line-reveal-delay", `${delay}ms`);
    line.classList.add("is-typing");
    line.addEventListener(
      "animationstart",
      () => {
        if (!shouldFollowFeed) {
          return;
        }
        const feedBottom = feed.getBoundingClientRect().bottom;
        const lineBottom = line.getBoundingClientRect().bottom;
        feed.scrollTop += Math.max(0, lineBottom - feedBottom);
      },
      { once: true },
    );
  }
  nextFeedLineRevealAt =
    firstRevealAt + newFeedLines.length * outputTypingDuration;
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
    if (nextFeedLineRevealAt <= performance.now()) {
      shouldFollowFeed ||=
        feed.scrollHeight - feed.scrollTop - feed.clientHeight <= 1;
      updateFeedTailVisibility();
    }
    feedLineCountBeforeSwap = feed.querySelectorAll(".feed-line").length;
    const currentRoundLink = assignmentSidebar?.querySelector(
      '.round-link[aria-current="true"]',
    );
    const focusedRoundLink = document.activeElement?.closest(".round-link");
    currentRoundHash = currentRoundLink?.hash ?? null;
    focusedRoundHash = assignmentSidebar?.contains(focusedRoundLink)
      ? focusedRoundLink.hash
      : null;
  });
  feed.addEventListener("htmx:afterSwap", (event) => {
    if (event.detail.target !== feed) {
      return;
    }
    typeNewFeedLines();
    if (shouldFollowFeed && nextFeedLineRevealAt <= performance.now()) {
      feed.scrollTop = feed.scrollHeight;
    }
    const currentRoundLink = assignmentSidebar?.querySelector(
      `.round-link[href="${currentRoundHash}"]`,
    );
    currentRoundLink?.setAttribute("aria-current", "true");
    const focusedRoundLink = assignmentSidebar?.querySelector(
      `.round-link[href="${focusedRoundHash}"]`,
    );
    focusedRoundLink?.focus({ preventScroll: true });
  });
}

if (assignmentSidebar !== null) {
  assignmentSidebar.addEventListener("click", (event) => {
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
    for (const otherLink of assignmentSidebar.querySelectorAll(".round-link")) {
      otherLink.removeAttribute("aria-current");
    }
    roundLink.setAttribute("aria-current", "true");
    const feedTop = feed.getBoundingClientRect().top;
    // A sticky header reports where it is pinned, not where its round begins.
    feedRound.style.position = "static";
    const roundTop = feedRound.getBoundingClientRect().top;
    feedRound.style.removeProperty("position");
    feed.scrollTo({
      top: feed.scrollTop + roundTop - feedTop,
      behavior: "smooth",
    });
  });
}
