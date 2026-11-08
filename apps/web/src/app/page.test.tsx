import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import results from "@/lib/results.generated.json";

const nav = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => nav }));
vi.mock("./actions", () => ({ signIn: vi.fn() }));

import HomePage from "./page";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

test("the front page says what Brimline is, and that it is fictional", () => {
  render(<HomePage />);
  expect(screen.getByText("The system behind a 3D printing shop")).toBeDefined();
  expect(screen.getByRole("heading", { level: 1 }).textContent).toContain("From a customer's message to a running print");
  const note = screen.getByRole("note");
  expect(note.textContent).toContain("all data are fictional");
  expect(note.textContent).toContain("machines are simulated");
});

test("three ways in, with the existing demo login (customer, planner, operator)", () => {
  render(<HomePage />);
  const names = screen.getAllByRole("button", { name: /^Try it as an? / }).map((b) => b.textContent);
  expect(names).toEqual(["Try it as a customerMia Chen", "Try it as a plannerPriya Nandakumar", "Try it as an operatorJonas Weber"]);
  const codes = [...document.querySelectorAll<HTMLInputElement>('input[name="user_code"]')].map((i) => i.value);
  expect(codes).toEqual(["U-HARBOR", "U-PLANNER", "U-OPERATOR"]);
});

test("the results strip shows the generated figures and their caveats, not typed ones", () => {
  render(<HomePage />);
  const strip = screen.getByRole("heading", { name: "Measured, not claimed" }).parentElement!;
  for (const r of results.items) expect(within(strip).getByText(r.value)).toBeDefined();
  for (const c of results.caveats) expect(within(strip).getByText(c)).toBeDefined();
});

test("the video has controls, no autoplay, and loads nothing until asked", () => {
  const { container } = render(<HomePage />);
  const video = container.querySelector("video")!;
  expect([video.controls, video.autoplay, video.getAttribute("preload")]).toEqual([true, false, "none"]);
  expect(video.getAttribute("poster")).toBe("/media/brimline-demo-poster.jpg");
});

test("links to the public source and README; no sign-up form, no prices", () => {
  const { container } = render(<HomePage />);
  const links = [...container.querySelectorAll<HTMLAnchorElement>('a[href*="github.com"]')].map((a) => [a.textContent, a.getAttribute("href")]);
  expect(links).toEqual([
    ["The source code", "https://github.com/SalNexflow/brimline"],
    ["the README", "https://github.com/SalNexflow/brimline#readme"],
  ]);
  expect(container.querySelector('input[type="email"], input[type="password"]')).toBeNull();
  expect(container.textContent).not.toMatch(/[$€£]\s?\d/);
});

test("Try it signs in when the engine is awake, and goes through the waking page when it is not", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("awake", { status: 200 })));
  const submit = vi.spyOn(HTMLFormElement.prototype, "requestSubmit").mockImplementation(() => {});
  render(<HomePage />);
  fireEvent.click(screen.getByRole("button", { name: /Try it as a planner/ }));
  await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
  expect(nav.push).not.toHaveBeenCalled();
  cleanup();

  vi.stubGlobal("fetch", vi.fn(async () => new Response("asleep", { status: 503 })));
  render(<HomePage />);
  fireEvent.click(screen.getByRole("button", { name: /Try it as a customer/ }));
  await waitFor(() => expect(nav.push).toHaveBeenCalledWith("/login"));
  expect(submit).toHaveBeenCalledTimes(1); // not again
});
