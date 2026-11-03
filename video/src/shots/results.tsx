// Chapter 6: measured results and the end card (storyboard shots 17a, 17b, 18).
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";

import numbers from "../numbers.generated.json";
import { NumberCard, Sfx, Typewriter } from "../kit";
import { easeOut, Page } from "../parts";
import { color } from "../theme";

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

/** Shot 17a (3.6 s): late jobs at 80 jobs, the earliest-due-date rule against ours. */
export function LateJobs() {
  const frame = useCurrentFrame();
  const s = numbers.scheduler;
  const ours = interpolate(frame, [14, 30], [0, 1], { ...clamp, easing: easeOut });
  return (
    <Page>
      <AbsoluteFill>
        <NumberCard
          big={
            <>
              <span style={{ color: color.muted, fontWeight: 500 }}>{s.lateEdd}</span>
              <span style={{ opacity: ours, color: color.muted, fontWeight: 400 }}> → </span>
              <span style={{ opacity: ours }}>{s.lateOurs}</span>
            </>
          }
          lines={[{ text: `80 jobs. Late: earliest-due-date ${s.lateEdd}, ours ${s.lateOurs}`, at: 4, strong: true }]}
          source={s.lateSource}
          sourceAt={16}
        />
        {/* "Ours" arrives after the arrow. */}
        <Sfx sound="tick" at={14} volume={0.5} />
      </AbsoluteFill>
    </Page>
  );
}

/** Shot 17b (3.0 s): plans where ours beat the baseline. */
export function BetterOn() {
  const s = numbers.scheduler;
  return (
    <Page>
      <AbsoluteFill>
        <NumberCard
          big={`${s.better} / ${s.instances}`}
          lines={[{ text: `Better on ${s.better} of ${s.instances} plans`, at: 4, strong: true }]}
          source={s.source}
          sourceAt={14}
        />
      </AbsoluteFill>
    </Page>
  );
}

/** Shot 18 (4.2 s): the end card, typed out, then held. */
export function EndCard() {
  return (
    <Page>
      <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", gap: 30 }}>
        <Typewriter text="BRIMLINE" from={4} size={96} perChar={2} cursor={false} />
        <Typewriter text="FICTIONAL SHOP · FAKE DATA · SIMULATED MACHINES" from={24} size={34} perChar={0.9} cursor={false} />
        <Typewriter text="github.com/SalNexflow/brimline" from={70} size={34} perChar={0.9} />
      </AbsoluteFill>
    </Page>
  );
}
