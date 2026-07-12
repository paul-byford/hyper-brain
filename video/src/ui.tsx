import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import {C} from "./theme";
import {MONO, SANS} from "./fonts";

// A spring-driven entrance: fade up a few px. Returns a style object to spread onto any element.
export const useRise = (delay = 0, dist = 20) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const p = spring({
    frame: frame - delay,
    fps,
    config: {damping: 200, mass: 0.7},
    durationInFrames: 24,
  });
  return {opacity: p, transform: `translateY(${(1 - p) * dist}px)`} as const;
};

// The persistent backdrop. Rendered once, behind every scene, so it never flickers on a cut.
export const Background: React.FC = () => (
  <AbsoluteFill style={{backgroundColor: C.ground}}>
    <AbsoluteFill
      style={{
        background: `radial-gradient(1300px 760px at 50% -14%, ${C.signal}20, transparent 62%)`,
      }}
    />
    <AbsoluteFill
      style={{
        background: `radial-gradient(1000px 1000px at 88% 118%, ${C.steel}12, transparent 55%)`,
      }}
    />
    {/* Faint baseline grid, for a "systems" texture without noise. */}
    <AbsoluteFill
      style={{
        backgroundImage: `linear-gradient(${C.hair}55 1px, transparent 1px), linear-gradient(90deg, ${C.hair}55 1px, transparent 1px)`,
        backgroundSize: "72px 72px",
        opacity: 0.35,
        maskImage:
          "radial-gradient(1200px 700px at 50% 45%, black, transparent 78%)",
        WebkitMaskImage:
          "radial-gradient(1200px 700px at 50% 45%, black, transparent 78%)",
      }}
    />
    {/* Vignette to seat the content. */}
    <AbsoluteFill
      style={{
        boxShadow: "inset 0 0 340px 90px rgba(0,0,0,0.55)",
      }}
    />
  </AbsoluteFill>
);

// Every scene lives inside this: fades in at the top, out at the tail, so cuts breathe.
// The opening scene passes enterFade={false} so frame 0 is already full content (it is the
// poster GitHub shows before play), and only the tail fade-out remains.
export const Scene: React.FC<{children: React.ReactNode; enterFade?: boolean}> = ({
  children,
  enterFade = true,
}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const opacity = enterFade
    ? interpolate(
        frame,
        [0, 14, durationInFrames - 16, durationInFrames],
        [0, 1, 1, 0],
        {extrapolateLeft: "clamp", extrapolateRight: "clamp"}
      )
    : interpolate(frame, [durationInFrames - 16, durationInFrames], [1, 0], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      });
  return (
    <AbsoluteFill
      style={{
        opacity,
        alignItems: "center",
        justifyContent: "center",
        fontFamily: SANS,
      }}
    >
      {children}
    </AbsoluteFill>
  );
};

// Small mono uppercase kicker above a headline.
export const Eyebrow: React.FC<{
  children: React.ReactNode;
  delay?: number;
  color?: string;
}> = ({children, delay = 0, color = C.signalInk}) => {
  const s = useRise(delay, 12);
  return (
    <div
      style={{
        ...s,
        fontFamily: MONO,
        fontSize: 22,
        letterSpacing: 6,
        textTransform: "uppercase",
        color,
        display: "flex",
        alignItems: "center",
        gap: 16,
      }}
    >
      <span
        style={{
          width: 34,
          height: 1,
          background: color,
          opacity: 0.7,
        }}
      />
      {children}
    </div>
  );
};

// The HB monogram used in the app's landing brand.
export const Glyph: React.FC<{size?: number; style?: React.CSSProperties}> = ({
  size = 96,
  style,
}) => (
  <div
    style={{
      width: size,
      height: size,
      flex: "none",
      display: "grid",
      placeItems: "center",
      background: "#14130c",
      border: `2px solid ${C.signal}`,
      color: C.signal,
      fontFamily: SANS,
      fontWeight: 800,
      fontSize: size * 0.34,
      letterSpacing: -1,
      borderRadius: 4,
      boxShadow: `0 0 60px ${C.signal}30`,
      ...style,
    }}
  >
    HB
  </div>
);

export const Pill: React.FC<{
  children: React.ReactNode;
  accent?: string;
  style?: React.CSSProperties;
}> = ({children, accent = C.signal, style}) => (
  <div
    style={{
      fontFamily: MONO,
      fontSize: 22,
      color: C.ink,
      padding: "12px 20px",
      borderRadius: 999,
      border: `1px solid ${accent}66`,
      background: `${accent}14`,
      whiteSpace: "nowrap",
      ...style,
    }}
  >
    {children}
  </div>
);
