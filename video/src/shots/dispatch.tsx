// Chapter 5: machine dispatch (storyboard shots 14 to 16).
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";

import boxes from "../../public/stills/boxes.json";
import numbers from "../numbers.generated.json";
import { NumberCard, project, target, Window } from "../kit";
import { Caption, Page, rise } from "../parts";
import { color, font, shadow } from "../theme";

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const PROCEED = boxes["dispatch-proposal"].proceed;
const ROW = boxes["dispatch-log"].row;

/** Every dispatch shot says the machines are simulated. */
function Simulated() {
  return (
    <div style={{ position: "absolute", right: 120, top: 34, fontFamily: font.mono, fontSize: 24, letterSpacing: "0.08em", color: color.muted }}>
      SIMULATED MACHINES
    </div>
  );
}

/** Shot 14 (4.8 s): the agent's proposal; a person presses Proceed. */
export function AgentProposes() {
  const frame = useCurrentFrame();
  const proposals = target("dispatch-proposal", "proposals");
  const proceed = target("dispatch-proposal", "proceed");
  const keys = [
    { f: 0, x: proposals.x, y: proposals.y, z: 1.4 },
    { f: 40, x: proposals.x, y: proposals.y + 30, z: 2.0 },
    { f: 144, x: proposals.x, y: proposals.y + 40, z: 2.1 },
  ];
  const at = project(keys, frame, proceed);
  const ring = rise(frame, 96, 118);
  return (
    <Page>
      <Window still="dispatch-proposal" keys={keys} />
      <div
        style={{
          position: "absolute",
          left: at.x - (PROCEED.w * at.scale) / 2,
          top: at.y - (PROCEED.h * at.scale) / 2,
          width: PROCEED.w * at.scale,
          height: PROCEED.h * at.scale,
          borderRadius: 999,
          border: `4px solid ${color.accent}`,
          opacity: ring > 0 && ring < 1 ? 1 - ring : 0,
          scale: String(1 + ring * 0.5),
        }}
      />
      <Simulated />
      <Caption text="An agent proposes. A person says go." from={18} out={141} />
    </Page>
  );
}

/** Shot 15 (3.6 s): the call is logged as allowed, and the machine's state changes in place. */
export function CallChecked() {
  const frame = useCurrentFrame();
  const row = target("dispatch-log", "row");
  const running = frame >= 54;
  const pop = rise(frame, 54, 66);
  const glow = interpolate(frame, [10, 24, 60], [0, 1, 0.35], clamp);
  const keys = [{ f: 0, x: row.x, y: row.y, z: 1.9 }, { f: 108, x: row.x + 40, y: row.y, z: 2.0 }];
  // The logged call's row, highlighted at its measured place in the still.
  const tl = project(keys, frame, { x: ROW.x, y: ROW.y }, 110, 150, 1100);
  const br = project(keys, frame, { x: ROW.x + ROW.w, y: ROW.y + ROW.h }, 110, 150, 1100);
  return (
    <Page>
      <Window still="dispatch-log" left={110} top={150} width={1100} keys={keys} />
      <div style={{ position: "absolute", left: Math.max(tl.x, 110), top: tl.y, width: Math.min(br.x, 1210) - Math.max(tl.x, 110), height: br.y - tl.y, borderRadius: 12, boxShadow: `0 0 0 4px rgba(74,63,192,${glow * 0.6})` }} />
      <div style={{ position: "absolute", left: 1290, top: 300, width: 520, padding: "36px 40px", borderRadius: 24, background: color.glassStrong, boxShadow: shadow }}>
        <div style={{ fontSize: 46, fontWeight: 700 }}>CNC-1</div>
        <div style={{ fontSize: 30, color: color.muted, marginTop: 6 }}>grbl · simulated</div>
        <div
          key={running ? "run" : "idle"}
          style={{
            display: "inline-block",
            marginTop: 28,
            padding: "10px 26px",
            borderRadius: 999,
            fontSize: 36,
            fontWeight: 700,
            background: running ? color.okBg : "#eef0f8",
            color: running ? color.okFg : color.fg,
            scale: String(running ? 0.92 + pop * 0.08 : 1),
            opacity: running ? 0.4 + pop * 0.6 : 1,
          }}
        >
          {running ? "▶ Running" : "○ Idle"}
        </div>
      </div>
      <Caption text="Code checks every call." from={18} out={105} />
    </Page>
  );
}

/** Shot 16 (3.6 s): the dispatch eval, dev and held-out scenarios together. */
export function DispatchNumber() {
  const d = numbers.dispatch;
  return (
    <Page>
      <AbsoluteFill>
        <NumberCard
          big={`${d.unsafeThrough} / ${d.unsafeCalls}`}
          lines={[
            { text: `Unsafe calls passed: ${d.unsafeThrough} of ${d.unsafeCalls}.`, at: 4, strong: true },
            { text: `Without Proceed: ${d.withoutProceed}`, at: 10 },
          ]}
          source={d.source}
          sourceAt={16}
        />
      </AbsoluteFill>
    </Page>
  );
}

