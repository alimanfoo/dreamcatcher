"use strict";

const feed = document.querySelector(".feed-records");
const feedTail = document.querySelector(".feed-tail");
const assignmentSidebar = document.querySelector(".assignment-sidebar");
const queuedFeedLines = [];
let shouldFollowFeed = false;
let feedLineCountBeforeSwap = 0;
let isRevealingFeedLine = false;
let currentRoundHash = null;
let focusedRoundHash = null;

function revealNextFeedLine() {
  if (isRevealingFeedLine || queuedFeedLines.length === 0) {
    return;
  }
  const line = queuedFeedLines.shift();
  isRevealingFeedLine = true;
  line.classList.remove("is-awaiting-reveal");
  line.classList.add("is-typing");
  line.addEventListener(
    "animationend",
    () => {
      line.classList.remove("is-typing");
      isRevealingFeedLine = false;
      revealNextFeedLine();
    },
    { once: true },
  );
}

function queueNewFeedLines() {
  const newFeedLines = [...feed.querySelectorAll(".feed-line")].slice(
    feedLineCountBeforeSwap,
  );
  if (
    window.matchMedia("(prefers-reduced-motion: reduce)").matches ||
    newFeedLines.length === 0
  ) {
    return;
  }
  for (const line of newFeedLines) {
    line.classList.add("is-awaiting-reveal");
  }
  queuedFeedLines.push(...newFeedLines);
  revealNextFeedLine();
}

if (feed !== null) {
  feed.scrollTop = feed.scrollHeight;
  if (feedTail !== null) {
    feedTail.addEventListener("click", () => {
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
    shouldFollowFeed =
      feed.scrollHeight - feed.scrollTop - feed.clientHeight <= 1;
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
    queueNewFeedLines();
    if (shouldFollowFeed) {
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
    for (const otherLink of assignmentSidebar.querySelectorAll(".round-link")) {
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
