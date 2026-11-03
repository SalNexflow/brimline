import type { CSSProperties, ReactNode } from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame } from "remotion";

import { color, font, shadow } from "./theme";

/** Entries ease out (expo-like), exits ease in and are faster (motion-video skill). */
export const easeOut = Easing.bezier(0.16, 1, 0.3, 1);
export const easeIn = Easing.bezier(0.7, 0, 0.84, 0);
const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

/** 0 to 1 over [from, to] frames, eased out. */
export function rise(frame: number, from: number, to: number): number {
  return interpolate(frame, [from, to], [0, 1], { ...clamp, easing: easeOut });
}

/** The page: off-white with pastel washes in the corners, as in the app. A slow drift keeps it alive. */
export function Page({ children }: { children: ReactNode }) {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill
      style={{
        backgroundColor: color.bg,
        backgroundImage: [
          `radial-gradient(900px 700px at ${100 + frame * 0.02}% 0%, ${color.washLilac}, transparent 70%)`,
          `radial-gradient(800px 650px at 0% 100%, ${color.washPeach}, transparent 70%)`,
          `radial-gradient(700px 560px at 100% 100%, ${color.washTeal}, transparent 70%)`,
        ].join(","),
        fontFamily: font.sans,
        color: color.fg,
      }}
    >
      {children}
    </AbsoluteFill>
  );
}

/**
 * A caption: the words rise in one after another (45 ms apart) and hold until `out`, then fade
 * faster than they came. On a glass pill, so it never sits on a busy region unprotected.
 */
export function Caption({ text, from, out, style }: { text: string; from: number; out: number; style?: CSSProperties }) {
  const frame = useCurrentFrame();
  const words = text.split(" ");
  const leave = interpolate(frame, [out - 6, out], [1, 0], { ...clamp, easing: easeIn });
  return (
    <div
      style={{
        position: "absolute",
        left: "50%",
        bottom: 96,
        translate: "-50% 0",
        padding: "18px 40px",
        borderRadius: 999,
        background: color.glassStrong,
        boxShadow: shadow,
        fontSize: 50,
        fontWeight: 600,
        letterSpacing: "-0.01em",
        whiteSpace: "nowrap",
        opacity: Math.min(rise(frame, from, from + 9), leave),
        ...style,
      }}
    >
      {words.map((w, i) => {
        const t = rise(frame, from + i * 1.4, from + i * 1.4 + 12);
        // The space sits between the words: an inline-block word would drop a space inside it.
        return (
          <span key={i}>
            {i > 0 ? " " : null}
            <span style={{ display: "inline-block", opacity: t, translate: `0 ${(1 - t) * 18}px`, filter: `blur(${(1 - t) * 6}px)` }}>{w}</span>
          </span>
        );
      })}
    </div>
  );
}

/** The small line under a number that says where it came from. */
export function Source({ text, from }: { text: string; from: number }) {
  const frame = useCurrentFrame();
  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        bottom: 72,
        textAlign: "center",
        fontFamily: font.mono,
        fontSize: 26,
        letterSpacing: "0.04em",
        color: color.muted,
        opacity: rise(frame, from, from + 12),
      }}
    >
      {text}
    </div>
  );
}
