import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test } from "vitest";

import { THEME_KEY, THEME_SCRIPT, parseTheme } from "@/lib/theme";

import { ThemeSwitch } from "./theme-switch";

const html = document.documentElement;

beforeEach(() => {
  localStorage.clear();
  delete html.dataset.theme;
});
afterEach(cleanup);

test("the script in <head> applies a saved choice and ignores anything else", () => {
  for (const [saved, expected] of [["dark", "dark"], ["light", "light"], ["purple", undefined], [null, undefined]] as const) {
    delete html.dataset.theme;
    if (saved === null) localStorage.removeItem(THEME_KEY);
    else localStorage.setItem(THEME_KEY, saved);
    new Function(THEME_SCRIPT)();
    expect(html.dataset.theme).toBe(expected);
  }
});

test("only light and dark are choices; anything else follows the system", () => {
  expect([parseTheme("light"), parseTheme("dark"), parseTheme("Dark"), parseTheme(null)]).toEqual(["light", "dark", "system", "system"]);
});

test("the switch has three named choices, System by default", () => {
  render(<ThemeSwitch />);
  expect(screen.getByRole("group", { name: "Colour theme" })).toBeTruthy();
  const checked = screen.getAllByRole("radio").map((r) => [(r as HTMLInputElement).value, (r as HTMLInputElement).checked]);
  expect(checked).toEqual([["system", true], ["light", false], ["dark", false]]);
});

test("choosing Dark sets the page and remembers it; System forgets it", () => {
  render(<ThemeSwitch />);
  fireEvent.click(screen.getByRole("radio", { name: "Dark" }));
  expect(html.dataset.theme).toBe("dark");
  expect(localStorage.getItem(THEME_KEY)).toBe("dark");
  expect((screen.getByRole("radio", { name: "Dark" }) as HTMLInputElement).checked).toBe(true);

  fireEvent.click(screen.getByRole("radio", { name: "Light" }));
  expect([html.dataset.theme, localStorage.getItem(THEME_KEY)]).toEqual(["light", "light"]);

  fireEvent.click(screen.getByRole("radio", { name: "System" }));
  expect(html.dataset.theme).toBeUndefined();
  expect(localStorage.getItem(THEME_KEY)).toBeNull();
});

test("a choice made in another tab is applied here too", () => {
  render(<ThemeSwitch />);
  localStorage.setItem(THEME_KEY, "dark");
  act(() => {
    window.dispatchEvent(new StorageEvent("storage", { key: THEME_KEY, newValue: "dark" }));
  });
  expect(html.dataset.theme).toBe("dark");
  expect((screen.getByRole("radio", { name: "Dark" }) as HTMLInputElement).checked).toBe(true);
});
