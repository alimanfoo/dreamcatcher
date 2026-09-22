"use strict";

const feed = document.querySelector(".feed-records");
const feedTail = document.querySelector(".feed-tail");
const assignmentSidebar = document.querySelector(".assignment-sidebar");
let shouldFollowFeed = false;

if (feed !== null && feedTail !== null) {
  feedTail.addEventListener("click", () => {
    feed.scrollTo({
      top: feed.scrollHeight,
      behavior: "instant",
    });
  });
}

if (feed !== null) {
  feed.addEventListener("htmx:beforeSwap", (event) => {
    if (event.detail.target !== feed) {
      return;
    }
    shouldFollowFeed =
      feed.scrollHeight - feed.scrollTop - feed.clientHeight <= 1;
  });
  feed.addEventListener("htmx:afterSwap", (event) => {
    if (event.detail.target === feed && shouldFollowFeed) {
      feed.scrollTop = feed.scrollHeight;
    }
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
