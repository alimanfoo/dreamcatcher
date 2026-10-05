"use strict";

// A refresh never opens or closes a details element; only the reader does.
Idiomorph.defaults.callbacks.beforeAttributeUpdated = (attribute, element) =>
  !(attribute === "open" && element.matches("details"));
