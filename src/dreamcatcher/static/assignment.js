"use strict";

const feed = document.querySelector(".feed-records");
const feedTail = document.querySelector(".feed-tail");
const roundLinks = document.querySelectorAll(".round-link");
const feedOutputs = document.querySelectorAll(
  ".feed-line:not(.round-boundary) .feed-content",
);
const latestFeedOutput = feedOutputs.item(feedOutputs.length - 1);

if (
  latestFeedOutput !== null &&
  !window.matchMedia("(prefers-reduced-motion: reduce)").matches
) {
  const characterCount = Math.max(latestFeedOutput.textContent.length, 1);
  const duration = Math.min(Math.max(characterCount * 12, 180), 900);
  const steps = Math.min(characterCount, 80);
  latestFeedOutput.style.setProperty("--typing-duration", `${duration}ms`);
  latestFeedOutput.style.setProperty("--typing-steps", steps);
  latestFeedOutput.classList.add("is-typing");
  latestFeedOutput.addEventListener(
    "animationend",
    () => {
      latestFeedOutput.classList.remove("is-typing");
      latestFeedOutput.style.removeProperty("--typing-duration");
      latestFeedOutput.style.removeProperty("--typing-steps");
    },
    { once: true },
  );
}

if (feed !== null && feedTail !== null) {
  feedTail.addEventListener("click", () => {
    feed.scrollTo({
      top: feed.scrollHeight,
      behavior: "instant",
    });
  });
}

for (const roundLink of roundLinks) {
  roundLink.addEventListener("click", (event) => {
    const feedRound = document.querySelector(roundLink.hash);
    if (feed === null || feedRound === null) {
      return;
    }
    event.preventDefault();
    for (const otherLink of roundLinks) {
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
