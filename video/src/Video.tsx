// The whole video, shot by shot as in STORYBOARD.md (77.4 s at 30 fps). Cuts are hard and on the
// beat (18 frames); chapters change with a short blur dissolve.
import type { ComponentType } from "react";
import { AbsoluteFill, Sequence } from "remotion";

import { Dissolve } from "./kit";
import { color } from "./theme";
import { Boundary, QuoteNumber, ReadsMessage } from "./shots/boundary";
import { BoardCheck, MutationsCaught, PlantedError } from "./shots/checker";
import { AgentProposes, CallChecked, DispatchNumber } from "./shots/dispatch";
import { DataField, NameCard, PanelStack, PlanCheckRun } from "./shots/opening";
import { BetterOn, EndCard, LateJobs } from "./shots/results";
import { MovedNumber, PlanMoves, PrinterDown } from "./shots/replan";

/** [storyboard shot, component, length in frames, dissolve in, dissolve out] */
export const SHOTS: [string, ComponentType, number, boolean, boolean][] = [
  ["1", DataField, 144, true, false],
  ["2", PlanCheckRun, 108, false, false],
  ["3", PanelStack, 144, false, true],
  ["4", NameCard, 36, true, true],
  ["5", ReadsMessage, 144, true, false],
  ["6", Boundary, 144, false, false],
  ["7", QuoteNumber, 162, false, true],
  ["8", BoardCheck, 144, true, false],
  ["9", PlantedError, 108, false, false],
  ["10", MutationsCaught, 108, false, true],
  ["11", PrinterDown, 144, true, false],
  ["12", PlanMoves, 144, false, false],
  ["13", MovedNumber, 108, false, true],
  ["14", AgentProposes, 144, true, false],
  ["15", CallChecked, 108, false, false],
  ["16", DispatchNumber, 108, false, true],
  ["17a", LateJobs, 108, true, false],
  ["17b", BetterOn, 90, false, false],
  ["18", EndCard, 126, false, false],
];

export const TOTAL_FRAMES = SHOTS.reduce((n, [, , len]) => n + len, 0);

export function Video() {
  let from = 0;
  return (
    <>
      {/* The page colour under every shot, so a dissolve fades to the page, never to black. */}
      <AbsoluteFill style={{ backgroundColor: color.bg }} />
      {SHOTS.map(([id, Shot, len, inT, outT]) => {
        const start = from;
        from += len;
        return (
          <Sequence key={id} from={start} durationInFrames={len} name={`Shot ${id}`}>
            <Dissolve length={len} fadeIn={inT} fadeOut={outT}>
              <Shot />
            </Dissolve>
          </Sequence>
        );
      })}
    </>
  );
}
