import React from "react";
import {AbsoluteFill, Audio, interpolate, Series, staticFile} from "remotion";
import {Background} from "./ui";
import {
  SceneAccess,
  SceneAgents,
  SceneAnswer,
  SceneGraph,
  SceneOKF,
  SceneOpen,
  SceneOutro,
  SceneProblem,
  SceneStudioDemo,
  SceneTeam,
  SceneTenant,
} from "./scenes";

export const FPS = 30;

// Scene running order and lengths (frames @ 30fps). Kept in lock-step with the cut list in
// audio/make_soundtrack.py so the music breathes with the edit. Total stays under a minute.
const TIMELINE: {c: React.FC; d: number}[] = [
  {c: SceneOpen, d: 135}, //        0.00 -  4.50  logo
  {c: SceneProblem, d: 110}, //     4.50 -  8.17  the problem
  {c: SceneTeam, d: 140}, //        8.17 - 12.83  one brain for the whole company
  {c: SceneGraph, d: 150}, //      12.83 - 17.83  connected knowledge
  {c: SceneAnswer, d: 165}, //     17.83 - 23.33  cited answers
  {c: SceneAccess, d: 140}, //     23.33 - 28.00  scoped access
  {c: SceneStudioDemo, d: 260}, // 28.00 - 36.67  Studio: draft-from-URL (centerpiece)
  {c: SceneOKF, d: 170}, //        36.67 - 42.33  Open Knowledge Format
  {c: SceneTenant, d: 165}, //     42.33 - 47.83  no installs, in-tenant GCP
  {c: SceneAgents, d: 140}, //     47.83 - 52.50  agent team
  {c: SceneOutro, d: 140}, //      52.50 - 57.17  outro
];

export const DURATION = TIMELINE.reduce((n, s) => n + s.d, 0); // 1715 frames = 57.17s

export const HyperBrainPromo: React.FC = () => (
  <AbsoluteFill>
    <Background />
    <Audio
      src={staticFile("soundtrack.mp3")}
      volume={(f) =>
        interpolate(f, [0, 24, DURATION - 40, DURATION], [0, 0.85, 0.85, 0], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        })
      }
    />
    <Series>
      {TIMELINE.map(({c: SceneComp, d}, i) => (
        <Series.Sequence key={i} durationInFrames={d}>
          <SceneComp />
        </Series.Sequence>
      ))}
    </Series>
  </AbsoluteFill>
);
