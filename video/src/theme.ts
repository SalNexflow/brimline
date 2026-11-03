// The app's soft-glass tokens (apps/web/src/app/theme.css, light mode), so the video matches the app.
export const color = {
  bg: "#f3f4fa",
  fg: "#1b1d2a",
  muted: "#545a6b",
  accent: "#4a3fc0",
  border: "#dcdfeb",
  glass: "rgba(255, 255, 255, 0.74)",
  glassStrong: "rgba(255, 255, 255, 0.9)",
  glassEdge: "rgba(70, 76, 130, 0.12)",
  okBg: "#e3f4e8",
  okFg: "#1d5e2c",
  errorBg: "#fbe6e3",
  errorFg: "#8a1c11",
  washPeach: "#fde3d3",
  washPink: "#f9dbe8",
  washLilac: "#e6defb",
  washBlue: "#d9e6fb",
  washTeal: "#d3f0ec",
  bars: ["#2a5f9e", "#1f6e47", "#6f45a8", "#9a4f08", "#1d6b77", "#94285f"],
};

export const font = {
  sans: '"Segoe UI Variable Display", "Segoe UI Variable", "Segoe UI", system-ui, sans-serif',
  mono: '"Cascadia Mono", Consolas, "Courier New", monospace',
};

export const shadow = "0 0 0 1px rgba(70, 76, 130, 0.12), 0 6px 18px rgba(60, 64, 120, 0.07), 0 22px 44px rgba(60, 64, 120, 0.06)";

export const FPS = 30;
/** 100 BPM: a beat is 0.6 s, 18 frames. Cuts land on beats (STORYBOARD.md). */
export const BEAT = 18;
