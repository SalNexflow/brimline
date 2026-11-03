import { Composition } from "remotion";

import { CheckerChapter } from "./shots/checker";
import { FPS } from "./theme";
import { TOTAL_FRAMES, Video } from "./Video";

export function Root() {
  return (
    <>
      <Composition id="Brimline" component={Video} durationInFrames={TOTAL_FRAMES} fps={FPS} width={1920} height={1080} />
      {/* The approved test shot (storyboard shots 8 to 10), kept for comparison. */}
      <Composition id="TestChecker" component={CheckerChapter} durationInFrames={360} fps={FPS} width={1920} height={1080} />
    </>
  );
}
