import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

// The server actions call the engine; here only whether the form calls them matters.
const actions = vi.hoisted(() => ({
  decide: vi.fn(async () => ({ error: null })),
  planDay: vi.fn(async () => ({ error: null })),
}));
vi.mock("./actions", () => actions);
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: () => {} }) }));

import { DecisionForm } from "./forms";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const stale = {
  scheduleId: 5,
  approveKey: "approve-key",
  discardKey: "discard-key",
  canApprove: false,
  reason: "It cannot be approved: jobs or work changed since it was made.",
};

test("a stale draft offers Plan again beside the reason, and pressing it starts a new plan", async () => {
  render(<DecisionForm {...stale} replan={{ idempotencyKey: "plan-key", busy: false }} />);
  expect((screen.getByRole("button", { name: "Approve plan" }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText(stale.reason)).toBeTruthy();
  const again = screen.getByRole("button", { name: "Plan again" });
  expect((again as HTMLButtonElement).disabled).toBe(false);
  // A screen reader hears why, too: the button is described by the reason.
  expect(document.getElementById(again.getAttribute("aria-describedby") ?? "")?.textContent).toBe(stale.reason);

  fireEvent.click(again);
  await waitFor(() => expect(actions.planDay).toHaveBeenCalledTimes(1));
  const form = (actions.planDay.mock.calls[0] as unknown[])[1] as FormData;
  expect(form.get("idempotency_key")).toBe("plan-key");
  expect(actions.decide).not.toHaveBeenCalled();
});

test("Plan again waits while a plan is already being made", () => {
  render(<DecisionForm {...stale} replan={{ idempotencyKey: "plan-key", busy: true }} />);
  expect((screen.getByRole("button", { name: "Plan again" }) as HTMLButtonElement).disabled).toBe(true);
});

test("a draft that can be approved shows no Plan again", () => {
  render(<DecisionForm {...stale} canApprove reason={null} />);
  expect((screen.getByRole("button", { name: "Approve plan" }) as HTMLButtonElement).disabled).toBe(false);
  expect(screen.queryByRole("button", { name: "Plan again" })).toBeNull();
});
