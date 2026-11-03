// Chapter 3 of the storyboard: the independent checker (shots 8, 9 and 10, 12 s).
import { AbsoluteFill, interpolate, Sequence, useCurrentFrame } from "remotion";

import numbers from "../numbers.generated.json";
import { target, Window } from "../kit";
import { Caption, easeOut, Page, rise, Source } from "../parts";
import { color, font, shadow } from "../theme";

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

/** Shot 8 (4.8 s): the real board in a floating window; the camera eases in on the check badge. */
function BoardCheck() {
  const badge = target("board-check", "badge");
  return (
    <Page>
      <Window
        still="board-check"
        keys={[
          { f: 0, x: 960, y: 540, z: 1 },
          { f: 30, x: 960, y: 540, z: 1 },
          { f: 96, x: badge.x, y: badge.y + 60, z: 2.1 },
        ]}
      />
      <Caption text="A second program checks every plan." from={18} out={138} />
    </Page>
  );
}

/** Shot 9 (3.6 s): an illustration. One bar slides into another's time; the check fails, by name. */
function PlantedError() {
  const frame = useCurrentFrame();
  const slide = interpolate(frame, [12, 40], [0, 1], { ...clamp, easing: easeOut });
  const failed = frame >= 48;
  const pop = rise(frame, 48, 60);
  const lanes = [
    [{ x: 40, w: 260, c: color.bars[0] }, { x: 360, w: 300, c: color.bars[2] }, { x: 760, w: 220, c: color.bars[4] }],
    [{ x: 120, w: 340, c: color.bars[1] }, { x: 560 - slide * 240, w: 280, c: color.bars[3] }],
    [{ x: 60, w: 200, c: color.bars[5] }, { x: 420, w: 380, c: color.bars[0] }],
  ];
  return (
    <Page>
      <div style={{ position: "absolute", left: 120, top: 90, fontFamily: font.mono, fontSize: 26, letterSpacing: "0.06em", color: color.muted }}>
        ILLUSTRATION: A PLANTED ERROR
      </div>
      <div
        style={{
          position: "absolute",
          left: "50%",
          top: 160,
          translate: "-50% 0",
          padding: "16px 36px",
          borderRadius: 999,
          fontSize: 40,
          fontWeight: 600,
          background: failed ? color.errorBg : color.okBg,
          color: failed ? color.errorFg : color.okFg,
          boxShadow: shadow,
          scale: String(failed ? 0.94 + pop * 0.06 : 1),
        }}
      >
        {failed ? "✗ Independent check: failed · machine_overlap" : "✓ Independent check: passed"}
      </div>
      <div
        style={{
          position: "absolute",
          left: (1920 - 1100) / 2,
          top: 290,
          width: 1100,
          padding: "36px 40px",
          borderRadius: 24,
          background: color.glass,
          boxShadow: shadow,
          display: "grid",
          gap: 22,
          scale: String(1 + interpolate(frame, [0, 108], [0, 0.02], clamp)),
        }}
      >
        {lanes.map((lane, i) => (
          <div key={i} style={{ position: "relative", height: 64, borderBottom: i < 2 ? `1px solid ${color.border}` : undefined }}>
            {lane.map((b, j) => (
              <div key={j} style={{ position: "absolute", left: b.x, width: b.w, top: 8, height: 48, borderRadius: 10, background: b.c, opacity: 0.92 }} />
            ))}
            {i === 1 && slide > 0.6 ? (
              <div
                style={{
                  position: "absolute",
                  left: 320,
                  width: 140,
                  top: 0,
                  height: 64,
                  borderRadius: 10,
                  border: `4px solid ${color.errorFg}`,
                  background: "repeating-linear-gradient(135deg, rgba(138,28,17,0.25) 0 10px, transparent 10px 20px)",
                  opacity: rise(frame, 40, 50),
                }}
              />
            ) : null}
          </div>
        ))}
      </div>
      <Caption text="It shares no code with the scheduler." from={15} out={102} />
    </Page>
  );
}

/** Shot 10 (3.6 s): the measured number arrives large and out of focus and settles sharp. */
function MutationsCaught() {
  const frame = useCurrentFrame();
  const settle = interpolate(frame, [0, 20], [0, 1], { ...clamp, easing: easeOut });
  const meaning = rise(frame, 18, 32);
  const n = (x: number) => x.toLocaleString("en-US");
  return (
    <Page>
      <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
        <div
          style={{
            fontSize: 210,
            fontWeight: 700,
            letterSpacing: "-0.03em",
            fontVariantNumeric: "tabular-nums",
            scale: String(1.6 - settle * 0.6 + interpolate(frame, [20, 108], [0, 0.02], clamp)),
            filter: `blur(${(1 - settle) * 24}px)`,
            opacity: 0.2 + settle * 0.8,
            marginTop: -80,
          }}
        >
          {n(numbers.checker.caught)} <span style={{ color: color.muted, fontWeight: 400 }}>/</span> {n(numbers.checker.applied)}
        </div>
        <div style={{ fontSize: 58, fontWeight: 600, color: color.accent, opacity: meaning, translate: `0 ${(1 - meaning) * 18}px` }}>
          planted rule breaks caught
        </div>
      </AbsoluteFill>
      <Source text={`${numbers.checker.kinds} kinds of corruption · ${numbers.checker.source}`} from={30} />
    </Page>
  );
}

/** Shots 8 to 10 back to back: hard cuts on the beat (144 and 252 frames). */
export { BoardCheck, MutationsCaught, PlantedError };

export function CheckerChapter() {
  return (
    <>
      <Sequence durationInFrames={144}>
        <BoardCheck />
      </Sequence>
      <Sequence from={144} durationInFrames={108}>
        <PlantedError />
      </Sequence>
      <Sequence from={252} durationInFrames={108}>
        <MutationsCaught />
      </Sequence>
    </>
  );
}
