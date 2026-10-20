"use strict";

// A refresh never opens or closes a details element; only the reader does.
Idiomorph.defaults.callbacks.beforeAttributeUpdated = (attribute, element) =>
  !(attribute === "open" && element.matches("details"));

// A refresh names its alert in data-refresh-alert. A failed refresh keeps
// what the page shows and gives the server's reason; a successful one clears it.
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
  if (message === null) {
    return;
  }
  alert.textContent = `Refresh failed. Showing what the page last read. ${message.textContent}`;
  alert.hidden = false;
});
