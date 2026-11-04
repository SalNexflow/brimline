// The colour theme a person picked: "system" (follow the device), "light" or "dark" (D199).
// Kept in this browser only (localStorage), so it costs the server nothing. theme.css does the rest:
// <html data-theme="light|dark"> sets color-scheme, and every colour token follows it.

export const THEME_KEY = "brimline-theme";
const CHANGED = "brimline-theme-change";

export type ThemeChoice = "system" | "light" | "dark";

export function parseTheme(value: unknown): ThemeChoice {
  return value === "light" || value === "dark" ? value : "system";
}

/** Inlined in <head>, so the saved theme applies before the first paint (no flash of the other
    theme). Kept tiny and dependency-free; app/theme-switch.test.tsx runs this exact string. */
export const THEME_SCRIPT = `try{var t=localStorage.getItem(${JSON.stringify(THEME_KEY)});if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}`;

function apply(choice: ThemeChoice): void {
  if (choice === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = choice;
}

export function storedTheme(): ThemeChoice {
  try {
    return parseTheme(localStorage.getItem(THEME_KEY));
  } catch {
    return "system"; // storage blocked (private mode, settings): the page still follows the device
  }
}

export function setTheme(choice: ThemeChoice): void {
  try {
    if (choice === "system") localStorage.removeItem(THEME_KEY);
    else localStorage.setItem(THEME_KEY, choice);
  } catch {
    // Not remembered, but still applied to this page.
  }
  apply(choice);
  window.dispatchEvent(new Event(CHANGED));
}

/** For useSyncExternalStore: this tab's changes, and another tab's (the storage event). */
export function subscribeTheme(onChange: () => void): () => void {
  const fromOtherTab = (e: StorageEvent) => {
    if (e.key !== THEME_KEY && e.key !== null) return;
    apply(parseTheme(e.newValue));
    onChange();
  };
  window.addEventListener(CHANGED, onChange);
  window.addEventListener("storage", fromOtherTab);
  return () => {
    window.removeEventListener(CHANGED, onChange);
    window.removeEventListener("storage", fromOtherTab);
  };
}
