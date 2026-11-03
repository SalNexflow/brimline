// Chapter 4: re-plan after a breakdown (storyboard shots 11 to 13).
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";

import numbers from "../numbers.generated.json";
import boxes from "../../public/stills/boxes.json";
import { NumberCard, project, target, Window } from "../kit";
import { Caption, Page, rise } from "../parts";
import { color } from "../theme";

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const BOXES_ENTRY = boxes["disruption-entry"].box;
const APPROVE = boxes["replan-approve"].approve;

/** Shot 11 (4.8 s): the planner types what broke; the camera is close on the message box. */
export function PrinterDown() {
  const frame = useCurrentFrame();
  const box = BOXES_ENTRY;
  const keys = [{ f: 0, x: box.x + box.w / 2, y: box.y + box.h / 2, z: 1.6 }, { f: 30, x: box.x + box.w / 2, y: box.y + box.h / 2, z: 2.4 }];
  // The typed words appear left to right: a cover in the field's own white slides away with a caret.
  // The words take about the left half of the field (from the still).
  const typed = interpolate(frame, [36, 80], [0, 1], clamp);
  const a = project(keys, frame, { x: box.x + 14, y: box.y + 10 });
  const b = project(keys, frame, { x: box.x + box.w * 0.55, y: box.y + box.h - 10 });
  return (
    <Page>
      <Window still="disruption-entry" keys={keys} />
      <div
        style={{
          position: "absolute",
          left: a.x + (b.x - a.x) * typed,
          top: a.y,
          width: (b.x - a.x) * (1 - typed),
          height: b.y - a.y,
          background: "#ffffff",
          borderLeft: typed < 1 ? `3px solid ${color.fg}` : undefined,
        }}
      />
      <Caption text="A printer goes down." from={18} out={141} />
    </Page>
  );
}

/** Shot 12 (4.8 s): the draft's changes, then a person presses Approve. */
export function PlanMoves() {
  const frame = useCurrentFrame();
  const moves = target("replan-diff", "moves");
  const approve = target("replan-approve", "approve");
  const second = frame >= 84;
  const keys = [{ f: 84, x: approve.x + 300, y: approve.y, z: 1.8 }, { f: 144, x: approve.x + 300, y: approve.y, z: 1.9 }];
  const at = project(keys, frame, approve);
  const ring = rise(frame, 102, 124);
  const press = interpolate(frame, [98, 103, 110], [1, 0.9, 1], clamp);
  return (
    <Page>
      {second ? (
        <>
          <Window still="replan-approve" keys={keys} />
          {/* The press: a ring spreads from the button (drawn over the still at its measured place). */}
          <div
            style={{
              position: "absolute",
              left: at.x - (APPROVE.w * at.scale) / 2,
              top: at.y - (APPROVE.h * at.scale) / 2,
              width: APPROVE.w * at.scale,
              height: APPROVE.h * at.scale,
              borderRadius: 999,
              border: `4px solid ${color.accent}`,
              opacity: ring > 0 && ring < 1 ? 1 - ring : 0,
              scale: String((1 + ring * 0.5) * press),
            }}
          />
        </>
      ) : (
        <Window still="replan-diff" keys={[{ f: 0, x: moves.x, y: moves.y + 260, z: 1.3 }, { f: 84, x: moves.x, y: moves.y + 340, z: 1.35 }]} />
      )}
      <Caption text="The plan moves. A person approves." from={18} out={141} />
    </Page>
  );
}

/** Shot 13 (3.6 s): jobs moved against the fair baseline, at the same lateness. */
export function MovedNumber() {
  const r = numbers.replan;
  return (
    <Page>
      <AbsoluteFill>
        <NumberCard
          big={
            <>
              {r.movedConfigured} <span style={{ fontSize: 110, color: color.muted, textDecoration: "line-through", fontWeight: 500 }}>{r.movedBaseline}</span>
            </>
          }
          lines={[{ text: `jobs moved instead of ${r.movedBaseline}, same lateness`, at: 6, strong: true }]}
          source={r.source}
          sourceAt={18}
        />
      </AbsoluteFill>
    </Page>
  );
}
