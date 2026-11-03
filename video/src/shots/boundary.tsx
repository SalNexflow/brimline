// Chapter 2: AI versus code (storyboard shots 5 to 7).
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";

import numbers from "../numbers.generated.json";
import { NumberCard, target, Window } from "../kit";
import { Caption, easeOut, Page, rise } from "../parts";
import { color, font, shadow } from "../theme";

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

/** Shot 5 (4.8 s): the customer's own words on the quote, then the lines read from them. */
export function ReadsMessage() {
  const msg = target("quote-draft", "message");
  const lines = target("quote-draft", "lines");
  return (
    <Page>
      <Window
        still="quote-draft"
        keys={[
          { f: 0, x: 960, y: 540, z: 1 },
          { f: 24, x: 960, y: 540, z: 1 },
          // Zoom no further than the message's full width (1,120 px of the still) fits the window.
          { f: 60, x: msg.x, y: msg.y, z: 1.6 },
          { f: 84, x: msg.x, y: msg.y, z: 1.6 },
          { f: 120, x: lines.x, y: lines.y, z: 1.6 },
        ]}
      />
      <Caption text="AI reads the customer's message." from={18} out={141} />
    </Page>
  );
}

/** Shot 6 (4.8 s): the boundary. Words become data on the AI side; the price is computed on the code side. */
export function Boundary() {
  const frame = useCurrentFrame();
  const line = interpolate(frame, [6, 30], [0, 1], { ...clamp, easing: easeOut });
  // What the model returns: a due *rule* ("by Friday"); the date itself is resolved by code.
  const chips = ["20", "phone stands", "PETG, black", "by Friday"];
  const total = target("quote-price", "total");
  const rules = target("quote-price", "byRules");
  // The totals and "Calculated by the shop's price rules, not by AI." sit on the left of the page.
  const focus = { x: 720, y: (total.y + rules.y) / 2 - 20 };
  const panel = (side: "left" | "right") => ({
    position: "absolute" as const,
    top: 120,
    [side]: 110,
    width: 760,
    height: 640,
    borderRadius: 24,
    background: color.glass,
    boxShadow: shadow,
    padding: "44px 48px",
  });
  return (
    <Page>
      <div style={panel("left")}>
        <div style={{ fontFamily: font.mono, fontSize: 28, letterSpacing: "0.08em", color: color.muted }}>AI · WORDS INTO DATA</div>
        <div style={{ marginTop: 36, fontSize: 38, lineHeight: 1.4, borderLeft: `5px solid ${color.border}`, paddingLeft: 24, opacity: rise(frame, 6, 18) }}>
          “Hi! 20 phone stands, black PETG, need by Friday.”
        </div>
        <div style={{ marginTop: 40, display: "flex", flexWrap: "wrap", gap: 16 }}>
          {chips.map((c, i) => {
            const t = rise(frame, 30 + i * 6, 44 + i * 6);
            return (
              <div key={c} style={{ padding: "12px 26px", borderRadius: 999, background: color.washLilac, fontSize: 34, fontWeight: 600, opacity: t, scale: String(0.9 + t * 0.1) }}>
                {c}
              </div>
            );
          })}
        </div>
      </div>
      <div style={{ position: "absolute", left: 958, top: 120, width: 4, height: 640 * line, borderRadius: 2, background: color.fg }} />
      <div style={panel("right")}>
        <div style={{ fontFamily: font.mono, fontSize: 28, letterSpacing: "0.08em", color: color.muted }}>CODE · PRICES, DATES, PERMISSIONS</div>
        <div style={{ position: "absolute", left: 30, right: 30, top: 120, bottom: 30, overflow: "hidden", borderRadius: 18, opacity: rise(frame, 40, 56) }}>
          <Window still="quote-price" left={0} top={0} width={700} keys={[{ f: 0, x: focus.x, y: focus.y, z: 3.3 }, { f: 144, x: focus.x, y: focus.y, z: 3.5 }]} />
        </div>
      </div>
      <Caption text="Code computes every price, date and permission." from={18} out={141} />
    </Page>
  );
}

/** Shot 7 (5.4 s): the quote-reading eval on unseen messages. */
export function QuoteNumber() {
  const q = numbers.quote;
  return (
    <Page>
      <AbsoluteFill>
        <NumberCard
          big={`${q.allRightPercent} %`}
          lines={[
            { text: `every field right on ${q.messages} unseen messages`, at: 6, strong: true },
            { text: `${q.harmfulErrors} harmful errors`, at: 24 },
          ]}
          source={q.source}
        />
      </AbsoluteFill>
    </Page>
  );
}
