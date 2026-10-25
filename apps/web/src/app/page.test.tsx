import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import HomePage from "./page";

afterEach(cleanup);

test("home page shows the product name as its main heading", () => {
  render(<HomePage />);

  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Brimline");
});

test("home page states that the data is synthetic", () => {
  render(<HomePage />);

  expect(screen.getByText(/all data is synthetic/i)).toBeDefined();
});
