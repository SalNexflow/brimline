// Builds every Brimline icon from the owner's logo (apps/web/brand/brimline-mark.webp, D201), and
// prints how well the mark stands out on the app's backgrounds. The artwork itself is never changed:
// it is trimmed of its empty margin, scaled, and set on a dark rounded tile, because its colours
// (a bright teal-to-green gradient) only read on dark.
//
//   node scripts/brand-icons.mjs
//
// Uses sharp, which Next.js already brings for image optimisation (no new dependency).

import { mkdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const WEB = join(ROOT, "apps", "web");
const sharp = createRequire(createRequire(join(WEB, "package.json")).resolve("next/package.json"))("sharp");

const SOURCE = join(WEB, "brand", "brimline-mark.webp");
const TILE = "#1b1d2a"; // the app's ink (theme.css --color-fg, light): dark in both themes

async function trimmed() {
  // The mark without its transparent margin.
  const { data, info } = await sharp(SOURCE).trim({ threshold: 1 }).png().toBuffer({ resolveWithObject: true });
  return { data, width: info.width, height: info.height };
}

/** The mark centred on a square dark tile. `fill` is the share of the tile's width the mark takes. */
async function onTile(mark, size, fill, radius) {
  const w = Math.round(size * fill);
  const scaled = await sharp(mark.data).resize({ width: w, kernel: "lanczos3" }).png().toBuffer();
  const meta = await sharp(scaled).metadata();
  const r = Math.round(size * radius);
  const tile = Buffer.from(
    `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}"><rect width="${size}" height="${size}" rx="${r}" fill="${TILE}"/></svg>`,
  );
  return sharp(tile)
    .composite([{ input: scaled, left: Math.round((size - w) / 2), top: Math.round((size - meta.height) / 2) }])
    .png()
    .toBuffer();
}

/** A .ico holding PNG images (every current browser reads PNG-in-ICO). */
function ico(pngs) {
  const header = Buffer.alloc(6 + 16 * pngs.length);
  header.writeUInt16LE(0, 0);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(pngs.length, 4);
  let offset = header.length;
  pngs.forEach(({ size, data }, i) => {
    const e = 6 + 16 * i;
    header.writeUInt8(size >= 256 ? 0 : size, e);
    header.writeUInt8(size >= 256 ? 0 : size, e + 1);
    header.writeUInt16LE(1, e + 4); // colour planes
    header.writeUInt16LE(32, e + 6); // bits per pixel
    header.writeUInt32LE(data.length, e + 8);
    header.writeUInt32LE(offset, e + 12);
    offset += data.length;
  });
  return Buffer.concat([header, ...pngs.map((p) => p.data)]);
}

// --- Contrast (WCAG relative luminance) ------------------------------------------------------------

const lum = ([r, g, b]) => {
  const c = (v) => ((v /= 255) <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
  return 0.2126 * c(r) + 0.7152 * c(g) + 0.0722 * c(b);
};
const ratio = (a, b) => {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
};
const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));

async function inkColours(mark) {
  // The gradient's two ends: the mean colour of solid pixels in the leftmost and rightmost tenths.
  const { data, info } = await sharp(mark.data).raw().toBuffer({ resolveWithObject: true });
  const band = (from, to) => {
    const sum = [0, 0, 0];
    let n = 0;
    for (let y = 0; y < info.height; y++)
      for (let x = Math.floor(from * info.width); x < Math.floor(to * info.width); x++) {
        const i = (y * info.width + x) * 4;
        if (data[i + 3] < 250) continue;
        sum[0] += data[i];
        sum[1] += data[i + 1];
        sum[2] += data[i + 2];
        n++;
      }
    return sum.map((s) => Math.round(s / n));
  };
  return { left: band(0, 0.1), right: band(0.9, 1) };
}

const mark = await trimmed();
const out = {
  // Next.js reads these from app/ and writes the <link rel="icon"> tags with their sizes.
  [join(WEB, "src", "app", "icon1.png")]: await onTile(mark, 16, 0.94, 0.19),
  [join(WEB, "src", "app", "icon2.png")]: await onTile(mark, 32, 0.84, 0.2),
  [join(WEB, "src", "app", "icon3.png")]: await onTile(mark, 512, 0.74, 0.22),
  // iOS rounds the corners itself: a full square.
  [join(WEB, "src", "app", "apple-icon.png")]: await onTile(mark, 180, 0.74, 0),
  // The in-app mark (the rail's 28 px tile, the sign-in page's larger one), wide enough for sharp screens.
  [join(WEB, "public", "brand", "mark.png")]: await sharp(mark.data).resize({ width: 192, kernel: "lanczos3" }).png().toBuffer(),
  // The product video's name card (video/src/shots/opening.tsx): about 100 px wide at 1080p, drawn at 3x.
  [join(ROOT, "video", "public", "brand", "mark.png")]: await sharp(mark.data).resize({ width: 300, kernel: "lanczos3" }).png().toBuffer(),
};
mkdirSync(join(ROOT, "video", "public", "brand"), { recursive: true });
for (const [file, data] of Object.entries(out)) writeFileSync(file, data);
writeFileSync(
  join(WEB, "src", "app", "favicon.ico"),
  ico([
    { size: 16, data: out[join(WEB, "src", "app", "icon1.png")] },
    { size: 32, data: out[join(WEB, "src", "app", "icon2.png")] },
  ]),
);

const { left, right } = await inkColours(mark);
console.log(`mark ${mark.width} x ${mark.height} px (trimmed); ends rgb(${left}) and rgb(${right})`);
for (const [name, bg] of [["light page #f3f4fa", "#f3f4fa"], ["white", "#ffffff"], ["dark page #0e1120", "#0e1120"], [`tile ${TILE}`, TILE]]) {
  console.log(`  on ${name}: ${ratio(left, hex(bg)).toFixed(2)}:1 to ${ratio(right, hex(bg)).toFixed(2)}:1`);
}
