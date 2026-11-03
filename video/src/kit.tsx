// Reusable shot parts (motion-video skill recipes): a camera on a real app still, a number card,
// kinetic words, a typewriter line, and the chapter dissolve.
import type { ReactNode } from "react";
import { AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame } from "remotion";

import boxes from "../public/stills/boxes.json";
import { easeIn, easeOut, rise, Source } from "./parts";
import { color, font, shadow } from "./theme";

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

type Box = { x: number; y: number; w: number; h: number };
const BOXES = boxes as Record<string, Record<string, Box>>;

/** The centre of a measured target in a still (CSS pixels of the 1920 x 1080 capture). */
export function target(still: string, key: string): { x: number; y: number } {
  const b = BOXES[still]?.[key];
  if (!b) throw new Error(`no measured box ${still}.${key}: capture the stills again`);
  return { x: b.x + b.w / 2, y: b.y + b.h / 2 };
}

/** A camera keyframe: at frame `f`, centre on (x, y) of the still at zoom `z` (1 = whole still). */
export type Key = { f: number; x: number; y: number; z: number };

/** Where the camera is at a frame: zoom, and the visible part's top-left in window pixels at zoom 1. */
export function camera(keys: Key[], frame: number, width: number) {
  const height = (width * 9) / 16;
  const k = width / 1920; // still pixels to window pixels
  const fs = keys.map((q) => q.f);
  const at = (pick: (q: Key) => number) => (keys.length === 1 ? pick(keys[0]!) : interpolate(frame, fs, keys.map(pick), { ...clamp, easing: easeOut }));
  const z = at((q) => q.z) * (1 + interpolate(frame, [0, 300], [0, 0.03], clamp));
  // The visible part is the window's size divided by the zoom, centred on the focus but kept inside
  // the still, so the camera never shows past the screenshot's edge.
  const rx = Math.min(Math.max(at((q) => q.x) * k - width / (2 * z), 0), width - width / z);
  const ry = Math.min(Math.max(at((q) => q.y) * k - height / (2 * z), 0), height - height / z);
  return { z, rx, ry, k };
}

/** A point of the still (CSS pixels of the capture) in page pixels, for drawing over the window. */
export function project(keys: Key[], frame: number, p: { x: number; y: number }, left = 260, top = 70, width = 1400) {
  const { z, rx, ry, k } = camera(keys, frame, width);
  return { x: left + (p.x * k - rx) * z, y: top + (p.y * k - ry) * z, scale: k * z };
}

/**
 * A real app still in a floating glass window, with a camera that eases between keyframes and
 * keeps drifting slightly so the shot is never static.
 */
export function Window({ still, keys, left = 260, top = 70, width = 1400, enter = 0 }: { still: string; keys: Key[]; left?: number; top?: number; width?: number; enter?: number }) {
  const frame = useCurrentFrame();
  const height = (width * 9) / 16;
  const { z, rx, ry } = camera(keys, frame, width);
  const shown = rise(frame, enter, enter + 15);
  return (
    <div
      style={{
        position: "absolute",
        left,
        top,
        width,
        height,
        borderRadius: 24,
        overflow: "hidden",
        boxShadow: shadow,
        border: "1px solid rgba(255,255,255,0.95)",
        background: color.bg,
        opacity: shown,
        translate: `0 ${(1 - shown) * 24}px`,
      }}
    >
      <Img
        src={staticFile(`stills/${still}.png`)}
        style={{
          width,
          height,
          transformOrigin: "0 0",
          scale: String(z),
          translate: `${-z * rx}px ${-z * ry}px`,
        }}
      />
    </div>
  );
}

/**
 * A measured number: it arrives large and out of focus and settles small and sharp; its meaning
 * follows. The value is never counted up: it is the measured value from the first frame.
 */
export function NumberCard({ big, lines, source, sourceAt = 30 }: { big: ReactNode; lines: { text: ReactNode; at: number; strong?: boolean }[]; source: string; sourceAt?: number }) {
  const frame = useCurrentFrame();
  const settle = interpolate(frame, [0, 20], [0, 1], { ...clamp, easing: easeOut });
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", gap: 18 }}>
      <div
        style={{
          fontSize: 200,
          fontWeight: 700,
          letterSpacing: "-0.03em",
          lineHeight: 1,
          fontVariantNumeric: "tabular-nums",
          scale: String(1.6 - settle * 0.6 + interpolate(frame, [20, 200], [0, 0.03], clamp)),
          filter: `blur(${(1 - settle) * 24}px)`,
          opacity: 0.2 + settle * 0.8,
          marginTop: -60,
        }}
      >
        {big}
      </div>
      {lines.map((l, i) => {
        const t = rise(frame, l.at, l.at + 14);
        return (
          <div key={i} style={{ fontSize: l.strong ? 56 : 48, fontWeight: 600, color: l.strong ? color.accent : color.fg, opacity: t, translate: `0 ${(1 - t) * 18}px`, textAlign: "center", maxWidth: 1500 }}>
            {l.text}
          </div>
        );
      })}
      <Source text={source} from={sourceAt} />
    </AbsoluteFill>
  );
}

/** Words that enter small, overshoot and settle, one after another; earlier ones stay. */
export function KineticWords({ words, every }: { words: string[]; every: number }) {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", flexDirection: "column", gap: 4 }}>
      {words.map((w, i) => {
        const f = frame - i * every;
        const s = interpolate(f, [0, 8, 14], [0.55, 1.08, 1], { ...clamp, easing: easeOut });
        const o = interpolate(f, [0, 6], [0, 1], clamp);
        return (
          <div key={w} style={{ fontSize: 150, fontWeight: 700, letterSpacing: "-0.035em", lineHeight: 1.05, opacity: o, scale: String(s) }}>
            {w}
          </div>
        );
      })}
    </AbsoluteFill>
  );
}

/** Monospace caps typed out with a block cursor (about 18 characters a second). */
export function Typewriter({ text, from, size = 44, perChar = 1.7, cursor = true }: { text: string; from: number; size?: number; perChar?: number; cursor?: boolean }) {
  const frame = useCurrentFrame();
  const n = Math.max(0, Math.min(text.length, Math.floor((frame - from) / perChar)));
  const blink = Math.floor(frame / 9) % 2 === 0;
  return (
    <div style={{ fontFamily: font.mono, fontSize: size, letterSpacing: "0.1em", whiteSpace: "pre" }}>
      {text.slice(0, n)}
      <span style={{ display: "inline-block", width: "0.62em", height: "1em", verticalAlign: "-0.12em", background: (blink || n < text.length) && (cursor || n < text.length) && frame >= from ? color.fg : "transparent" }} />
    </div>
  );
}

/** A chapter's blur dissolve: the scene softens out over its last frames and the next softens in. */
export function Dissolve({ children, length, fadeIn = true, fadeOut = true }: { children: ReactNode; length: number; fadeIn?: boolean; fadeOut?: boolean }) {
  const frame = useCurrentFrame();
  const inT = fadeIn ? interpolate(frame, [0, 10], [0, 1], { ...clamp, easing: easeOut }) : 1;
  const outT = fadeOut ? interpolate(frame, [length - 8, length], [1, 0], { ...clamp, easing: easeIn }) : 1;
  const t = Math.min(inT, outT);
  return <AbsoluteFill style={{ opacity: t, filter: t < 1 ? `blur(${(1 - t) * 14}px)` : undefined }}>{children}</AbsoluteFill>;
}
