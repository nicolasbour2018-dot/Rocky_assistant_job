// What HTMX does not do by itself, and nothing else (decision B4, criterion e): the server renders every state.
// - Keyboard shortcuts: a key activates the visible element marked data-key="<key>" (a click, or the focus for a
//   text field).
// - The wait (decision G6, Q8): the gesture is disabled while its request is on its way; a thin bar shows a wait
//   longer than 300 ms.
// - The window (decision G6, R2, R3): a fragment swapped into #fenetre-contenu opens the window; it closes by
//   « Fermer », Escape, or an answer that asks it (event « fenetre-fermer »).
(() => {
  "use strict";

  const TEXT_TYPES = new Set(["text", "search", "email", "password", "url", "number"]);
  const WINDOW = "fenetre";
  const WINDOW_CONTENT = "fenetre-contenu";

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
    // An open window or drawer (a manual popover, decision G4) takes the keys: nothing behind it moves.
    const open = [
      ...document.querySelectorAll("dialog[open]"),
      ...[...document.querySelectorAll("[popover='manual']")].filter((element) =>
        element.matches(":popover-open"),
      ),
    ];
    const scope = open.length ? open : [document];
    return scope.flatMap((root) => [...root.querySelectorAll(selector)]).find(isVisible) ?? null;
  };

  const act = (target) => (isTextField(target) ? target.focus() : target.click());

  // The window: one <dialog>, its content rendered by the server.
  const windowOf = () => document.getElementById(WINDOW);
  const closeWindow = () => {
    const dialog = windowOf();
    if (!dialog) {
      return;
    }
    if (dialog.open) {
      dialog.close();
    }
    document.getElementById(WINDOW_CONTENT).replaceChildren();
  };
  document.addEventListener("htmx:afterSwap", (event) => {
    if (event.detail.target?.id !== WINDOW_CONTENT) {
      return;
    }
    const dialog = windowOf();
    if (event.detail.target.childElementCount === 0) {
      closeWindow();
    } else if (!dialog.open) {
      dialog.showModal();
    }
  });
  document.addEventListener("fenetre-fermer", closeWindow);
  document.addEventListener("click", (event) => {
    if (event.target instanceof Element && event.target.closest("[data-close-window]")) {
      closeWindow();
    }
  });
  // Escape closes the window natively; its content goes with it.
  document.addEventListener(
    "close",
    (event) => {
      if (event.target === windowOf()) {
        document.getElementById(WINDOW_CONTENT).replaceChildren();
      }
    },
    true,
  );

  // Decision G6 (A8, constat B4 → C7): a key struck while an HTMX request is on its way waits, then is replayed once
  // the answer is swapped and wired (after « settle »): the panel it asks for (the reasons after « i ») is there. A
  // navigation drops the keys waiting; so does an answer that leaves no element for them.
  const onTheirWay = new Set();
  let waiting = [];
  let navigating = false;
  let busyTimer = null;

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

  // Decision G6 (Q8): the wait is shown after 300 ms only; a quick answer shows nothing.
  const showWait = () => {
    if (busyTimer === null) {
      busyTimer = setTimeout(() => document.documentElement.classList.add("is-busy"), 300);
    }
  };
  const endWait = () => {
    clearTimeout(busyTimer);
    busyTimer = null;
    document.documentElement.classList.remove("is-busy");
  };

  // The button that sent the request: itself, or the submitter of its form.
  const gestureOf = (detail) => {
    const submitter = detail.requestConfig?.triggeringEvent?.submitter;
    if (submitter instanceof HTMLButtonElement) {
      return submitter;
    }
    return detail.elt instanceof HTMLButtonElement ? detail.elt : null;
  };
  const disabledByUs = new Map();

  const settled = (event) => {
    const xhr = event.detail.xhr;
    onTheirWay.delete(xhr);
    const button = disabledByUs.get(xhr);
    if (button) {
      button.disabled = false;
      disabledByUs.delete(xhr);
    }
    if (!onTheirWay.size) {
      endWait();
    }
    // After the other listeners of the same event: the swapped element is wired by then.
    setTimeout(replay, 0);
  };

  document.addEventListener("htmx:beforeRequest", (event) => {
    const { xhr } = event.detail;
    onTheirWay.add(xhr);
    showWait();
    if (event.detail.requestConfig?.boosted) {
      navigating = true;
    }
    const button = gestureOf(event.detail);
    if (button && !button.disabled) {
      button.disabled = true;
      disabledByUs.set(xhr, button);
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
      // While typing, only Escape leaves the field (in the window too, which stays open: what is typed stays);
      // Enter submits its form natively.
      if (event.key === "Escape") {
        event.preventDefault();
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
