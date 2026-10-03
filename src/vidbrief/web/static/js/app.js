// Page behaviour. The Content-Security-Policy forbids inline handlers, so it is all wired here,
// through delegation because HTMX replaces parts of the page.
(() => {
  const root = document.documentElement;

  const prefersDark = () => window.matchMedia("(prefers-color-scheme: dark)").matches;

  const toggleTheme = () => {
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : prefersDark();
    const next = dark ? "light" : "dark";
    root.dataset.theme = next;
    try {
      localStorage.setItem("vidbrief-theme", next);
    } catch {
      // Not saved, but the switch still applies to this page.
    }
  };

  const canPaste = Boolean(navigator.clipboard && navigator.clipboard.readText);
  const canCopy = Boolean(navigator.clipboard && navigator.clipboard.writeText);

  const showClipboardButtons = (scope) => {
    if (canPaste) for (const button of scope.querySelectorAll("[data-paste]")) button.hidden = false;
    if (canCopy) for (const button of scope.querySelectorAll("[data-copy]")) button.hidden = false;
  };

  let toastTimer;

  const showToast = (message) => {
    const toast = document.querySelector("[data-toast]");
    if (!toast) return;
    toast.textContent = message;
    toast.classList.add("visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      toast.classList.remove("visible");
      // Emptied so that copying again is announced again.
      toastTimer = setTimeout(() => { toast.textContent = ""; }, 200);
    }, 2400);
  };

  const copy = async (button) => {
    const source = document.getElementById(button.dataset.copy);
    if (!source) return;
    try {
      await navigator.clipboard.writeText(source.content.textContent);
      showToast("Copied as Markdown");
    } catch {
      showToast("Couldn't copy. Use Download instead.");
    }
  };

  const paste = async (button) => {
    const input = button.closest(".url").querySelector("input");
    try {
      input.value = (await navigator.clipboard.readText()).trim();
      input.dispatchEvent(new Event("input", { bubbles: true }));
    } catch {
      // Permission denied: let the user paste with the keyboard instead.
    }
    input.focus();
  };

  document.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;
    if (target.closest("[data-theme-toggle]")) toggleTheme();
    const pasteButton = target.closest("[data-paste]");
    if (pasteButton) paste(pasteButton);
    const copyButton = target.closest("[data-copy]");
    if (copyButton) copy(copyButton);
  });

  // A new attempt should not keep showing the previous error.
  document.addEventListener("input", (event) => {
    if (event.target instanceof HTMLInputElement && event.target.name === "url") {
      const error = document.getElementById("url-error");
      if (error) error.textContent = "";
    }
  });

  // Elapsed time of a running job, counted on from the value the server rendered. HTMX
  // replaces the element on every update, and each new one starts from its own value.
  const clockStarts = new WeakMap();

  const formatClock = (total) => {
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const seconds = String(total % 60).padStart(2, "0");
    return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${seconds}` : `${minutes}:${seconds}`;
  };

  setInterval(() => {
    for (const clock of document.querySelectorAll("[data-elapsed]")) {
      if (!clockStarts.has(clock)) {
        clockStarts.set(clock, Date.now() - Number(clock.dataset.elapsed) * 1000);
      }
      clock.textContent = formatClock(Math.floor((Date.now() - clockStarts.get(clock)) / 1000));
    }
  }, 1000);

  showClipboardButtons(document);
  document.addEventListener("htmx:load", (event) => showClipboardButtons(event.target));
})();
