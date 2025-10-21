const STORAGE_KEY = "ai-meeting-theme";
const THEMES = ["light", "dark"];

export function getSystemTheme() {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return "dark";
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function getStoredTheme() {
  if (typeof window === "undefined") {
    return undefined;
  }
  const stored = window.localStorage.getItem(STORAGE_KEY);
  return THEMES.includes(stored) ? stored : undefined;
}

export function storeTheme(theme) {
  if (typeof window === "undefined") {
    return;
  }
  if (!THEMES.includes(theme)) {
    window.localStorage.removeItem(STORAGE_KEY);
    return;
  }
  window.localStorage.setItem(STORAGE_KEY, theme);
}

export function applyTheme(theme) {
  if (typeof document === "undefined") {
    return;
  }
  const normalized = THEMES.includes(theme) ? theme : getSystemTheme();
  document.documentElement.setAttribute("data-theme", normalized);
  document.body?.setAttribute("data-theme", normalized);
}

export function initializeTheme() {
  const stored = getStoredTheme();
  const theme = stored ?? getSystemTheme();
  applyTheme(theme);
  if (!stored) {
    storeTheme(theme);
  }
  return theme;
}

export function subscribeToSystemTheme(callback) {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return () => {};
  }
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  const listener = (event) => {
    callback(event.matches ? "dark" : "light");
  };
  media.addEventListener("change", listener);
  return () => media.removeEventListener("change", listener);
}

export const THEMES_AVAILABLE = [...THEMES];
