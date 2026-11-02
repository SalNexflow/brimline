import type { ReactNode } from "react";

import { engineClient } from "@/lib/engine";
import { engineAwake } from "@/lib/demo";
import { formatShopTime } from "@/lib/timeline";

import { WakeWatch } from "./wake-watch";
import { Waking } from "./waking";

/** On the hosted demo: the waking-up screen while the engine sleeps, and a plain banner. */
export async function DemoGate({ children }: { children: ReactNode }) {
  if (!(await engineAwake())) return <Waking />;
  const { data: status } = await engineClient().GET("/demo-status");
  return (
    <>
      {status?.demo_mode ? (
        <p className="demo-banner" role="note">
          Public demo: fictional shop, fake data, simulated machines, reset every night.
          {status.demo_time ? (
            <>
              {" "}
              <strong data-testid="demo-time">Demo time: {formatShopTime(status.demo_time, "Europe/Berlin")}</strong> (the
              shop&apos;s clock is pinned inside a shift, so planning and dispatch work at any hour).
            </>
          ) : null}
          {status.model_limit_reason
            ? ` AI is paused for you (${status.model_limit_reason}): replies are replayed from a recorded run where one exists, otherwise everything works by hand.`
            : ""}
        </p>
      ) : null}
      <WakeWatch>{children}</WakeWatch>
    </>
  );
}
