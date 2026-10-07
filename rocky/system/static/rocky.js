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

  // The element a key asks for, or null.
  const targetOf = (key) => {
    const selector = `[data-key="${CSS.escape(key)}"]`;
    // An open drawer (a manual popover, decision G4) takes the keys: Escape closes it, nothing behind it moves.
    const open = [...document.querySelectorAll("[popover='manual']")].filter((element) =>
      element.matches(":popover-open"),
    );
    const scope = open.length ? open : [document];
    return scope.flatMap((root) => [...root.querySelectorAll(selector)]).find(isVisible) ?? null;
  };

  const act = (target) => (isTextField(target) ? target.focus() : target.click());

  // Decision G6 (A8, constat B4 → C7): a key struck while an HTMX request is on its way waits, then is replayed once
  // the answer is swapped and wired (after « settle »): the panel it asks for (the reasons after « i ») is there. A
  // navigation drops the keys waiting; so does an answer that leaves no element for them.
  const onTheirWay = new Set();
  let waiting = [];
  let navigating = false;

  const replay = () => {
    if (onTheirWay.size) {
      return;
    }
    const keys = waiting;
    waiting = [];
    if (navigating) {
      navigating = false;
      return;
    }
    for (const key of keys) {
      const target = targetOf(key);
      if (target) {
        act(target);
      }
    }
  };

  const settled = (event) => {
    onTheirWay.delete(event.detail.xhr);
    // After the other listeners of the same event: the swapped element is wired by then.
    setTimeout(replay, 0);
  };

  document.addEventListener("htmx:beforeRequest", (event) => {
    onTheirWay.add(event.detail.xhr);
    if (event.detail.requestConfig?.boosted) {
      navigating = true;
    }
  });
  document.addEventListener("htmx:afterSettle", settled);
  // An answer that swaps nothing never settles.
  document.addEventListener("htmx:beforeSwap", (event) => {
    if (!event.detail.shouldSwap) {
      settled(event);
    }
  });
  for (const name of ["htmx:sendError", "htmx:timeout", "htmx:sendAbort"]) {
    document.addEventListener(name, settled);
  }

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
    if (onTheirWay.size) {
      event.preventDefault();
      waiting.push(key);
      return;
    }
    const target = targetOf(key);
    if (!target) {
      return;
    }
    event.preventDefault();
    act(target);
  });
})();
