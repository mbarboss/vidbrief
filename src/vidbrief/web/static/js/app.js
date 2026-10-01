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

  const showPasteButtons = (scope) => {
    if (!canPaste) return;
    for (const button of scope.querySelectorAll("[data-paste]")) button.hidden = false;
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
  });

  // A new attempt should not keep showing the previous error.
  document.addEventListener("input", (event) => {
    if (event.target instanceof HTMLInputElement && event.target.name === "url") {
      const error = document.getElementById("url-error");
      if (error) error.textContent = "";
    }
  });

  showPasteButtons(document);
  document.addEventListener("htmx:load", (event) => showPasteButtons(event.target));
})();
