---
name: motion-video
description: Plan and build Brimline's motion-design video (storyboard, shot recipes, timing, type, transitions, QC). Use for any work on the product video in video/.
---

# Motion-design video for Brimline

Learned from seven reference product videos (notes and measured cut statistics in
`references.md`). Their structure and craft are studied here; no branding, layout, asset or
footage from them is ever used (CLAUDE.md: do not imitate any real company's product or UI).

## Fixed rules for this project

- **Remotion** in a separate `video/` folder (React + TypeScript, like the web app). Ask before
  adding any npm package. Render with the repo's existing ffmpeg (`ffmpeg-static`).
- **1920 x 1080, 16:9, 30 fps**, about **75 s**. Text-only captions with animated type, no voice.
- **Music: CC0 only**, its source and licence recorded next to the file.
- **Every number on screen is read from the result files at render time** (`eval/results/*`,
  bench outputs), never typed (hard rule 11). A missing file fails the render.
- The app is shown in its **real, approved look**: screenshots or recordings from the showcase
  stack (`SHOWCASE=design`), fake data only.
- Process: **storyboard → one test shot → full video**, each approved by the user. Record any
  better approach in `docs/DECISIONS.md`.

## Pacing (measured, see references.md)

| Kind of piece | Median shot | Read as |
|---|---|---|
| Calm teaser (one continuous take, about 5 s per beat) | ~5 s beats | confident, premium |
| Teaser with cuts | 3.2 s | readable, still brisk |
| Launch montage | 1.4 s | energy; word cards ~0.8 s alternate with 1.4 s UI clips |
| Agency showreel | 1.6 s (quarter of shots under 0.7 s) | spectacle, hard to read |

For a 75 s piece read by recruiters and engineers: **story beats of 6 to 12 s**, each with
constant internal motion, separated by **word cards of 0.8 to 1.2 s**. Nothing a viewer must read
is on screen for less than its reading time: `0.5 s + words / 3` seconds (6 words: 2.5 s).
Cut on the music's beat grid (at 100 BPM a beat is 0.6 s; cuts land on beats, big moments on bars).

## Shot recipes

1. **Abstract data field.** The product's data drawn as shapes (lines merging into a path, nodes,
   bars), close-up, shallow depth of field (blur the near and far layers), slow drift. Opens a
   piece before any UI appears. For Brimline: jobs as lines converging onto machine lanes.
2. **Macro UI crop.** One interface element at 3 to 6 times its size, cropped off the frame edge,
   on a soft out-of-focus background; a slow push-in of 2 to 5 % over the shot; content builds in
   it (typed text at about 10 characters per second with a caret, a list filling in).
3. **Tilted panel stack.** Two or three real screens on planes tilted 15 to 25 degrees in depth,
   sliding up into place one after another (stagger 150 to 250 ms), with parallax as the camera
   drifts.
4. **Floating window with zoom-to-region.** The real screen as a window with a soft shadow on a
   calm background; the camera eases in on the region that matters, then out. Use when the
   viewer must read the UI.
5. **State change in place.** Show before and after in the same frame (a status pill flips, a bar
   moves, a check turns green) instead of two screenshots. Change is what the eye follows.
6. **Kinetic word.** One or two words very large; enter small, overshoot to fill the frame, settle
   (spring, about 400 ms); the second phrase arrives letter by letter. Use once or twice, not as
   the default.
7. **Number reveal.** The figure enters huge and out of focus and settles small and sharp (rack
   focus, 500 to 700 ms); its meaning slides in beside it a beat later ("37 / 36 scenarios").
   The number is never counted up from zero: it is the measured value from the first frame.
8. **Typewriter caption.** Monospace caps, wide letter-spacing, block cursor; types, holds, erases,
   types the next line. Good for the closing lines.
9. **Word roller.** A fixed word with a vertical list of alternatives rolling past a highlight
   ("checked by ___": code, the checker, a person).
10. **End card.** Name and one line, held 2 to 3 s in silence or on the last chord.

## Transitions (in order of preference)

- **Hard cut on the beat**: the default.
- **Push-through**: the camera moves into an element that becomes the next scene (a pill grows into
  the next panel).
- **Match cut**: a shape continues across the cut (a bar becomes a timeline lane).
- **Blur dissolve** (300 to 500 ms): only between chapters.
- **Mask wipe** driven by a moving element. Never stock wipes, spins or page curls.

## Camera

Never fully static: a slow drift or push on every shot. Depth from layers moving at different
speeds. Perspective tilt for panels; rack focus to move attention. Moves start and end eased.

## Type

- One sans family (the app's) plus one monospace for data and captions.
- Display words 120 to 200 px, captions 44 to 56 px, labels 28 to 32 px at 1080p.
- At most about 7 words on screen; one idea per card.
- Enter by mask-reveal, blur-to-sharp or a short rise (12 to 24 px); never fly in from afar.
  Letters or words stagger 30 to 60 ms.
- Keep 5 % safe margins; never put text over a busy region (blur or dim the region behind it).

## Easing and timing

- Entries 300 to 600 ms, ease-out (expo or quint). Exits 200 to 300 ms, ease-in: leaving is faster.
- Springs only for kinetic type and small UI pops (moderate damping, no wobble).
- Holds are long enough to read (see Pacing), then the next beat arrives on the grid.

## Colour and light

Per scene, a small palette from the theme tokens (soft glass: off-white, ink, indigo accent,
pastel washes). A soft glow or gradient bloom behind the hero element only. Dark scenes for drama,
light scenes for reading the UI. Text contrast at least 4.5:1, as in the app.

## Brimline story (75 s)

1. **Problem** (about 10 s): orders, machines, materials, a shop day that never goes to plan.
2. **AI versus code** (about 15 s): the model turns words into structured data; code computes
   prices, dates and permissions. Show the boundary as a line the AI side never crosses.
3. **The independent checker** (about 12 s): a plan is checked by code that shares nothing with
   the scheduler; a violation is caught.
4. **Re-plan after a breakdown** (about 12 s): a machine goes down, the plan moves, a person approves.
5. **Machine dispatch** (about 12 s): the agent proposes, a person presses Proceed, the guard checks
   each call, a simulated machine starts.
6. **Measured results** (about 10 s): numbers from the result files, then the end card.

## QC before showing the user

- Render, then check the result frame by frame: a contact sheet of every cut, and dense strips
  around each transition (`ffmpeg ... fps=8,tile=6x2`).
- Every caption readable at 1080p and on screen for its reading time; nothing in the safe margin.
- Every number traced to its source file.
- Cuts on beats; no shot static; no transition used more than its share.
- No real brand, product or UI anywhere in the frame.
