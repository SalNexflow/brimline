import type { ReactNode } from "react";

import { engineClient } from "@/lib/engine";
import { engineAwake } from "@/lib/demo";

import { Waking } from "./waking";

/** On the hosted demo: the waking-up screen while the engine sleeps, and a plain banner. */
export async function DemoGate({ children }: { children: ReactNode }) {
  if (!(await engineAwake())) return <Waking />;
  const { data: status } = await engineClient().GET("/demo-status");
  return (
    <>
      {status?.demo_mode ? (
        <p className="demo-banner" role="note">
          Public demo: fictional shop, fake data, reset every night.
          {status.model_limit_reason
            ? ` AI is paused for you (${status.model_limit_reason}): replies are replayed from a recorded run where one exists, otherwise everything works by hand.`
            : ""}
        </p>
      ) : null}
      {children}
    </>
  );
}
