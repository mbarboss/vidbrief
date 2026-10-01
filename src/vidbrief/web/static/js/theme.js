// Runs before the page renders, so a saved theme never flashes the other one first.
try {
  const saved = localStorage.getItem("vidbrief-theme");
  if (saved === "light" || saved === "dark") {
    document.documentElement.dataset.theme = saved;
  }
} catch {
  // Storage can be blocked (private windows, strict settings); the system theme still applies.
}
