import React from "react";
import {Composition} from "remotion";
import {DURATION, FPS, HyperBrainPromo} from "./HyperBrainPromo";

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="HyperBrainPromo"
      component={HyperBrainPromo}
      durationInFrames={DURATION}
      fps={FPS}
      width={1920}
      height={1080}
    />
  );
};
