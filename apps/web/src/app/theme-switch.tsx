"use client";

import { useSyncExternalStore } from "react";

import { setTheme, storedTheme, subscribeTheme, type ThemeChoice } from "@/lib/theme";

// A symbol and a word for each, so the choice never relies on colour or icon alone. U+FE0E asks for
// the text form of the sun, not an emoji.
const OPTIONS: [ThemeChoice, string, string][] = [
  ["system", "System", "◐"],
  ["light", "Light", "☀\uFE0E"],
  ["dark", "Dark", "☾"],
];

/** System, Light or Dark: three radio buttons drawn as one pill. The server cannot know the saved
    choice, so it renders "System" checked; the highlighted option is drawn from the theme the script
    in <head> already applied (globals.css), so it is right from the first paint, and the radio
    buttons catch up as soon as the page's script runs. */
export function ThemeSwitch() {
  const choice = useSyncExternalStore(subscribeTheme, storedTheme, () => "system" as ThemeChoice);
  return (
    <fieldset className="theme-switch">
      <legend className="visually-hidden">Colour theme</legend>
      {OPTIONS.map(([value, label, glyph]) => (
        <label key={value} className="theme-option" data-value={value}>
          <input
            type="radio"
            name="theme"
            value={value}
            checked={choice === value}
            onChange={() => setTheme(value)}
            className="visually-hidden"
          />
          <span aria-hidden="true">{glyph}</span> {label}
        </label>
      ))}
    </fieldset>
  );
}
