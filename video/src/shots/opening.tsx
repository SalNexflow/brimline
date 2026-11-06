// Chapter 1: opening (storyboard shots 1 to 4).
import { AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame } from "remotion";

import { KineticWords, Sfx } from "../kit";
import { Caption, easeOut, Page, rise } from "../parts";
import { color, font, shadow } from "../theme";

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

// The shop's machines, as the seed names them.
const MACHINES = ["CNC-1", "FDM-1", "FDM-2", "FDM-3", "FDM-4", "RESIN-1"];

/** Shot 1 (4.8 s): orders as lines drifting in from the left and converging onto six machine lanes. */
export function DataField() {
  const frame = useCurrentFrame();
  const laneY = (i: number) => 230 + i * 110;
  // Fixed pseudo-random starts, so every render is identical.
  const lines = Array.from({ length: 30 }, (_, i) => ({ y0: 90 + ((i * 397) % 900), lane: (i * 7) % 6, delay: (i * 11) % 40 }));
  const drift = interpolate(frame, [0, 144], [0, -60], clamp);
  return (
    <Page>
      <svg width={1920} height={1080} style={{ position: "absolute", translate: `${drift}px 0`, scale: String(1 + frame * 0.0003) }}>
        {lines.map((l, i) => {
          const p = interpolate(frame, [l.delay, l.delay + 70], [0, 1], { ...clamp, easing: easeOut });
          const y1 = laneY(l.lane);
          const d = `M -40 ${l.y0} C 700 ${l.y0}, 900 ${y1}, 1500 ${y1}`;
          const near = i % 5 === 0; // a few near lines, out of focus, for depth
          return (
            <path
              key={i}
              d={d}
              fill="none"
              stroke={near ? color.washLilac : color.accent}
              strokeOpacity={near ? 0.9 : 0.35}
              strokeWidth={near ? 9 : 2.2}
              pathLength={1}
              strokeDasharray="1 1"
              strokeDashoffset={1 - p}
              style={{ filter: near ? "blur(6px)" : undefined }}
            />
          );
        })}
        {MACHINES.map((m, i) => {
          const t = rise(frame, 30 + i * 4, 48 + i * 4);
          return (
            <g key={m} opacity={t}>
              <rect x={1500} y={laneY(i) - 26} width={230} height={52} rx={26} fill={color.glassStrong} stroke={color.border} />
              <text x={1615} y={laneY(i) + 10} textAnchor="middle" fontFamily={font.mono} fontSize={28} fill={color.fg}>
                {m}
              </text>
            </g>
          );
        })}
      </svg>
      <Sfx sound="whoosh" at={0} volume={0.4} />
      <Sfx sound="tick" at={MACHINES.map((_, i) => 30 + i * 4)} volume={0.5} />
      <Caption text="A made-to-order print and CNC shop." from={18} out={141} />
    </Page>
  );
}

/** Shot 2 (3.6 s): three kinetic lines that describe what the product does. */
export function PlanCheckRun() {
  return (
    <Page>
      <KineticWords words={["Plan it.", "Check it.", "Run it."]} every={24} />
    </Page>
  );
}

/** Shot 3 (4.8 s): three real screens on tilted planes, rising one after another, with parallax. */
export function PanelStack() {
  const frame = useCurrentFrame();
  const panels = [
    { still: "orders", x: 60, y: 260, d: 0, z: -120 },
    { still: "materials-short", x: 470, y: 170, d: 6, z: 0 },
    { still: "queues", x: 880, y: 80, d: 12, z: 120 },
  ];
  return (
    <Page>
      <AbsoluteFill style={{ perspective: 1800 }}>
        {panels.map((p) => {
          const t = rise(frame, p.d, p.d + 22);
          const par = interpolate(frame, [0, 144], [0, -30 - p.z / 6], clamp);
          return (
            <Img
              key={p.still}
              src={staticFile(`stills/${p.still}.png`)}
              style={{
                position: "absolute",
                left: p.x + par,
                top: p.y + (1 - t) * 160,
                width: 1000,
                height: (1000 * 9) / 16,
                borderRadius: 18,
                boxShadow: shadow,
                opacity: t,
                rotate: "y -18deg",
                transform: `rotateX(8deg) translateZ(${p.z}px)`,
              }}
            />
          );
        })}
      </AbsoluteFill>
      <Sfx sound="swish" at={panels.map((p) => p.d)} volume={0.35} />
      <Caption text="Orders, machines, materials, people." from={18} out={141} />
    </Page>
  );
}

/** Shot 4 (1.2 s): the name card. The end card says "fictional shop, fake data". */
export function NameCard() {
  const frame = useCurrentFrame();
  const t = interpolate(frame, [0, 12], [0, 1], { ...clamp, easing: easeOut });
  return (
    <Page>
      <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", flexDirection: "row", gap: 36 }}>
        {/* The owner's mark on the app's dark tile (D201), as in the app's nav rail. */}
        <div style={{ width: 120, height: 120, borderRadius: 30, background: color.fg, display: "grid", placeItems: "center", scale: String(0.8 + t * 0.2), opacity: t }}>
          <Img src={staticFile("brand/mark.png")} style={{ width: 96 }} />
        </div>
        <div style={{ fontSize: 150, fontWeight: 700, letterSpacing: "-0.035em", opacity: t, translate: `${(1 - t) * -20}px 0` }}>Brimline</div>
      </AbsoluteFill>
      <Sfx sound="pop" at={0} />
    </Page>
  );
}
