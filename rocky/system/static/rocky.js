// Keyboard shortcuts, and nothing else (decision B4, criterion e): the server renders every state.
// A key activates the visible element marked data-key="<key>": a click, or the focus for a text field.
(() => {
  "use strict";

  const TEXT_TYPES = new Set(["text", "search", "email", "password", "url", "number"]);

  const isTextField = (element) =>
    element instanceof HTMLTextAreaElement ||
    (element instanceof HTMLInputElement && TEXT_TYPES.has(element.type)) ||
    (element instanceof HTMLElement && element.isContentEditable) ||
    element instanceof HTMLSelectElement;

  const isVisible = (element) => element.getClientRects().length > 0;

  const keyOf = (event) =>
    event.key === "Enter" || event.key === "Escape" ? event.key : event.key.toLowerCase();

  document.addEventListener("keydown", (event) => {
    if (event.ctrlKey || event.metaKey || event.altKey || event.isComposing) {
      return;
    }
    if (isTextField(event.target)) {
      // While typing, only Escape leaves the field; Enter submits its form natively.
      if (event.key === "Escape") {
        event.target.blur();
      }
      return;
    }
    const key = keyOf(event);
    const target = [...document.querySelectorAll(`[data-key="${CSS.escape(key)}"]`)].find(isVisible);
    if (!target) {
      return;
    }
    event.preventDefault();
    if (isTextField(target)) {
      target.focus();
    } else {
      target.click();
    }
  });
})();
