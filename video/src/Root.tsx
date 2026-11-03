import { Composition } from "remotion";

import { CheckerChapter } from "./shots/checker";
import { FPS } from "./theme";

/** One composition per test shot for now; the full video joins the chapters once each is approved. */
export function Root() {
  return (
    <Composition id="TestChecker" component={CheckerChapter} durationInFrames={360} fps={FPS} width={1920} height={1080} />
  );
}
