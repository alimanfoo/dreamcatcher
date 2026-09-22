"use strict";

const feed = document.querySelector(".feed-records");
const feedTail = document.querySelector(".feed-tail");
const roundLinks = document.querySelectorAll(".round-link");

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
