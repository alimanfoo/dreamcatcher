"use strict";

// A refresh never opens or closes a details element; only the reader does.
Idiomorph.defaults.callbacks.beforeAttributeUpdated = (attribute, element) =>
  !(attribute === "open" && element.matches("details"));

// A refresh names its alert in data-refresh-alert. A failed refresh keeps
// what the page shows and gives the server's reason, or points to the
// terminal when no reason came back, as when the server has stopped. A
// successful refresh clears the alert.
document.body.addEventListener("htmx:afterRequest", (event) => {
  const alertId = event.detail.elt.dataset?.refreshAlert;
  const alert = alertId === undefined ? null : document.getElementById(alertId);
  if (alert === null) {
    return;
  }
  if (event.detail.successful) {
    alert.hidden = true;
    return;
  }
  const message = new DOMParser()
    .parseFromString(event.detail.xhr.response, "text/html")
    .querySelector(".error-message");
  alert.textContent =
    message === null
      ? "Refresh failed. Check the terminal running dreamcatcher."
      : `Refresh failed. Showing what the page last read. ${message.textContent}`;
  alert.hidden = false;
});

// The server never sees the fragment, so a theme link takes the page's own
// as it is followed, and switching theme keeps the reader where they were.
document.addEventListener("click", (event) => {
  const link = event.target.closest("a.theme-choice");
  if (link !== null) {
    link.hash = location.hash;
  }
});
