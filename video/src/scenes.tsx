import React from "react";
import {
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import {C} from "./theme";
import {MONO, SANS} from "./fonts";
import {Eyebrow, Glyph, Pill, Scene, useRise} from "./ui";

const H1: React.FC<{
  children: React.ReactNode;
  size?: number;
  style?: React.CSSProperties;
}> = ({children, size = 88, style}) => (
  <div
    style={{
      fontFamily: SANS,
      fontWeight: 700,
      fontSize: size,
      lineHeight: 1.05,
      letterSpacing: -2.5,
      color: C.ink,
      textAlign: "center",
      maxWidth: 1440,
      textWrap: "balance",
      ...style,
    }}
  >
    {children}
  </div>
);

const Line: React.FC<{delay: number; children: React.ReactNode}> = ({
  delay,
  children,
}) => <div style={useRise(delay, 26)}>{children}</div>;

// Pure (non-hook) reveal so it can be mapped over lists: ease-out fade + rise.
const rev = (frame: number, delay: number, dist = 14) => {
  const p = Math.max(0, Math.min(1, (frame - delay) / 12));
  const e = 1 - (1 - p) * (1 - p);
  return {opacity: e, transform: `translateY(${(1 - e) * dist}px)`} as const;
};

// ---------------------------------------------------------------- 1. Cold open
export const SceneOpen: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  // A gentle settle (never from zero), so frame 0 already shows the full logo lockup.
  const settle = spring({frame, fps, config: {damping: 200}, durationInFrames: 34});
  const scale = interpolate(settle, [0, 1], [0.985, 1]);
  const underline = interpolate(frame, [6, 46], [0, 360], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <Scene enterFade={false}>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 30,
          transform: `scale(${scale})`,
        }}
      >
        <Glyph size={128} />
        <div
          style={{
            fontFamily: SANS,
            fontWeight: 800,
            fontSize: 128,
            letterSpacing: -4,
            color: C.ink,
            transform: `translateY(${(1 - settle) * 6}px)`,
          }}
        >
          Hyper Brain
        </div>
        <div
          style={{
            width: underline,
            height: 3,
            background: `linear-gradient(90deg, transparent, ${C.signal}, transparent)`,
          }}
        />
        <div
          style={{
            fontFamily: MONO,
            fontSize: 24,
            letterSpacing: 8,
            textTransform: "uppercase",
            color: C.muted,
          }}
        >
          The Company&apos;s Shared Memory
        </div>
      </div>
    </Scene>
  );
};

// ---------------------------------------------------------------- 2. The problem
export const SceneProblem: React.FC = () => (
  <Scene>
    <H1 size={96}>
      <Line delay={4}>Your company knows a lot.</Line>
      <Line delay={26}>
        <span style={{color: C.signal}}>It just can&apos;t remember.</span>
      </Line>
    </H1>
  </Scene>
);

// ---------------------------------------------------------------- 3. Team / company
export const SceneTeam: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const members = ["Eng", "Sales", "Legal", "People", "Finance", "Product"];
  const cx = 560;
  const cy = 230;
  const R = 175;
  return (
    <Scene>
      <div style={{display: "flex", flexDirection: "column", alignItems: "center", gap: 40}}>
        <Eyebrow delay={4}>One company, one memory</Eyebrow>
        <svg width={1120} height={460} viewBox="0 0 1120 460">
          {members.map((m, i) => {
            const ang = (i / members.length) * Math.PI * 2 - Math.PI / 2;
            const x = cx + Math.cos(ang) * R;
            const y = cy + Math.sin(ang) * R;
            const draw = interpolate(frame, [14 + i * 6, 40 + i * 6], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });
            const p = spring({frame: frame - (14 + i * 6), fps, config: {damping: 130}});
            return (
              <g key={m}>
                <line
                  x1={cx}
                  y1={cy}
                  x2={x}
                  y2={y}
                  stroke={C.signal}
                  strokeOpacity={0.35}
                  strokeWidth={1.6}
                  pathLength={1}
                  strokeDasharray={1}
                  strokeDashoffset={1 - draw}
                />
                <g transform={`translate(${x},${y})`} opacity={p}>
                  <circle r={46} fill={C.panel} stroke={C.hair} strokeWidth={2} />
                  <text textAnchor="middle" dy={7} fontFamily={MONO} fontSize={20} fill={C.ink}>
                    {m}
                  </text>
                </g>
              </g>
            );
          })}
          {/* Central brain */}
          <g transform={`translate(${cx},${cy})`}>
            <circle r={74 + 4 * Math.sin(frame / 8)} fill={C.signal} fillOpacity={0.1} />
            <circle r={62} fill="#14130c" stroke={C.signal} strokeWidth={2.5} />
            <text
              textAnchor="middle"
              dy={12}
              fontFamily={SANS}
              fontWeight={800}
              fontSize={34}
              fill={C.signal}
            >
              HB
            </text>
          </g>
        </svg>
        <H1 size={68} style={{...useRise(46, 22)}}>
          Every team&apos;s knowledge, in one brain.
        </H1>
      </div>
    </Scene>
  );
};

// ---------------------------------------------------------------- 4. Knowledge graph
type Node = {id: string; x: number; y: number; c: string; r: number};
const G_NODES: Node[] = [
  {id: "a", x: 210, y: 150, c: C.signal, r: 15},
  {id: "b", x: 420, y: 90, c: C.ink, r: 10},
  {id: "c", x: 620, y: 190, c: C.signal, r: 13},
  {id: "d", x: 830, y: 110, c: C.steel, r: 11},
  {id: "e", x: 360, y: 300, c: C.ink, r: 9},
  {id: "f", x: 560, y: 360, c: C.steel, r: 12},
  {id: "g", x: 760, y: 320, c: C.signal, r: 10},
  {id: "h", x: 980, y: 260, c: C.ink, r: 10},
  {id: "i", x: 150, y: 320, c: C.steel, r: 9},
];
const G_EDGES: [string, string][] = [
  ["a", "b"], ["b", "c"], ["c", "d"], ["a", "e"], ["e", "f"],
  ["c", "f"], ["f", "g"], ["g", "h"], ["d", "h"], ["e", "i"], ["b", "e"], ["g", "c"],
];
const nodeById = (id: string) => G_NODES.find((n) => n.id === id)!;

export const SceneGraph: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  return (
    <Scene>
      <div style={{display: "flex", flexDirection: "column", alignItems: "center", gap: 44}}>
        <Eyebrow delay={4}>Connected knowledge</Eyebrow>
        <svg width={1120} height={430} viewBox="0 0 1120 430">
          {G_EDGES.map(([u, v], idx) => {
            const a = nodeById(u);
            const b = nodeById(v);
            const draw = interpolate(frame, [10 + idx * 3, 34 + idx * 3], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            });
            return (
              <line
                key={`${u}-${v}`}
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                stroke={C.signal}
                strokeOpacity={0.32}
                strokeWidth={1.6}
                pathLength={1}
                strokeDasharray={1}
                strokeDashoffset={1 - draw}
              />
            );
          })}
          {G_NODES.map((n, idx) => {
            const p = spring({
              frame: frame - (20 + idx * 4),
              fps,
              config: {damping: 120, mass: 0.6},
            });
            const pulse = 1 + 0.12 * Math.sin((frame - idx * 8) / 9);
            return (
              <g key={n.id}>
                <circle cx={n.x} cy={n.y} r={n.r * 2.4 * p} fill={n.c} fillOpacity={0.12} />
                <circle
                  cx={n.x}
                  cy={n.y}
                  r={n.r * p * pulse}
                  fill={n.c}
                  stroke={C.ground}
                  strokeWidth={2}
                />
              </g>
            );
          })}
        </svg>
        <H1 size={70} style={{...useRise(30, 22)}}>
          Every note, doc and message — one living graph.
        </H1>
      </div>
    </Scene>
  );
};

// ---------------------------------------------------------------- 5. Cited answers
export const SceneAnswer: React.FC = () => {
  const frame = useCurrentFrame();
  const question = "How do we detect fraud in real time?";
  const typed = Math.floor(
    interpolate(frame, [10, 46], [0, question.length], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    })
  );
  const caret = Math.floor(frame / 8) % 2 === 0;
  return (
    <Scene>
      <div style={{display: "flex", flexDirection: "column", alignItems: "center", gap: 36}}>
        <Eyebrow delay={4}>Grounded answers</Eyebrow>
        <div style={{width: 1180, display: "flex", flexDirection: "column", gap: 20}}>
          <div
            style={{
              ...useRise(6, 18),
              display: "flex",
              alignItems: "center",
              gap: 18,
              background: C.panel,
              border: `1px solid ${C.hair}`,
              borderRadius: 16,
              padding: "24px 30px",
            }}
          >
            <div
              style={{
                width: 14,
                height: 14,
                borderRadius: 999,
                border: `2px solid ${C.signal}`,
                borderRightColor: "transparent",
                transform: `rotate(${frame * 8}deg)`,
              }}
            />
            <span style={{fontFamily: SANS, fontSize: 34, color: C.ink}}>
              {question.slice(0, typed)}
              <span style={{opacity: caret && typed < question.length ? 1 : 0, color: C.signal}}>|</span>
            </span>
          </div>
          <div
            style={{
              ...useRise(56, 26),
              background: C.panel,
              border: `1px solid ${C.hair}`,
              borderLeft: `3px solid ${C.signal}`,
              borderRadius: 16,
              padding: "28px 34px",
              display: "flex",
              flexDirection: "column",
              gap: 18,
            }}
          >
            <div style={{fontFamily: SANS, fontSize: 30, lineHeight: 1.5, color: C.ink}}>
              Score each transaction inline against the streaming feature store, then hold
              anything above the risk threshold for step-up review
              <sup style={{color: C.signal, fontFamily: MONO, fontSize: 18}}> 1,2</sup>.
            </div>
            <div style={{display: "flex", gap: 12, flexWrap: "wrap"}}>
              {["real-time-scoring.md", "risk-thresholds.md", "feature-store.md"].map((cite, i) => (
                <div
                  key={cite}
                  style={{
                    ...rev(frame, 70 + i * 6, 12),
                    fontFamily: MONO,
                    fontSize: 20,
                    color: C.signalInk,
                    padding: "8px 14px",
                    borderRadius: 8,
                    background: `${C.signal}14`,
                    border: `1px solid ${C.signal}44`,
                  }}
                >
                  [{i + 1}] {cite}
                </div>
              ))}
            </div>
          </div>
        </div>
        <H1 size={62} style={{...useRise(96, 20)}}>
          Answers with citations. Never a guess.
        </H1>
      </div>
    </Scene>
  );
};

// ---------------------------------------------------------------- 6. Scoped access
export const SceneAccess: React.FC = () => {
  const domains = [
    {name: "commons", open: true},
    {name: "personal", open: true},
    {name: "finserv-ai", open: false},
    {name: "recruitment", open: false},
  ];
  return (
    <Scene>
      <div style={{display: "flex", flexDirection: "column", alignItems: "center", gap: 44}}>
        <Eyebrow delay={4}>Scoped access</Eyebrow>
        <div style={{display: "flex", gap: 26}}>
          {domains.map((d, i) => {
            const s = useRise(12 + i * 8, 24);
            const locked = !d.open;
            return (
              <div
                key={d.name}
                style={{
                  ...s,
                  width: 240,
                  height: 200,
                  borderRadius: 18,
                  background: C.panel,
                  border: `1px solid ${locked ? C.hair : C.signal + "66"}`,
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "space-between",
                  padding: 26,
                  opacity: locked ? 0.55 : (s.opacity as number),
                }}
              >
                <div style={{fontSize: 40}}>{locked ? "🔒" : "🔓"}</div>
                <div>
                  <div style={{fontFamily: MONO, fontSize: 26, color: C.ink}}>{d.name}</div>
                  <div
                    style={{
                      fontFamily: MONO,
                      fontSize: 17,
                      letterSpacing: 2,
                      textTransform: "uppercase",
                      color: locked ? C.faint : C.signalInk,
                      marginTop: 6,
                    }}
                  >
                    {locked ? "not granted" : "you can read"}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
        <H1 size={66} style={{...useRise(52, 22)}}>
          Everyone sees only what they may read.
        </H1>
      </div>
    </Scene>
  );
};

// ---------------------------------------------------------------- 7. Studio: draft-from-URL demo
type Seg = {t: string; c: string};
const StudioLine: React.FC<{
  frame: number;
  delay: number;
  segs: Seg[];
  indent?: number;
}> = ({frame, delay, segs, indent = 0}) => (
  <div
    style={{
      ...rev(frame, delay, 10),
      fontFamily: MONO,
      fontSize: 25,
      lineHeight: 1.62,
      paddingLeft: indent,
      whiteSpace: "pre",
    }}
  >
    {segs.map((s, i) => (
      <span key={i} style={{color: s.c}}>
        {s.t}
      </span>
    ))}
  </div>
);

export const SceneStudioDemo: React.FC = () => {
  const frame = useCurrentFrame();
  const url = "blog.acme.com/rollout-feature-flags";
  const typed = Math.floor(
    interpolate(frame, [8, 34], [0, url.length], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    })
  );
  const caret = Math.floor(frame / 8) % 2 === 0;
  const arrow = interpolate(frame, [40, 58], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  const key = (s: string) => ({t: s, c: C.signalInk});
  const val = (s: string) => ({t: s, c: C.ink});
  const dim = (s: string) => ({t: s, c: C.muted});
  const wl = (s: string) => ({t: s, c: C.steel});
  return (
    <Scene>
      <div style={{display: "flex", flexDirection: "column", alignItems: "center", gap: 30}}>
        <Eyebrow delay={2}>Content Studio</Eyebrow>
        <div style={{display: "flex", alignItems: "center", gap: 30}}>
          {/* Source URL + action */}
          <div style={{display: "flex", flexDirection: "column", gap: 16, width: 470}}>
            <div
              style={{
                ...useRise(4, 20),
                background: C.panel,
                border: `1px solid ${C.hair}`,
                borderRadius: 14,
                padding: "22px 24px",
                fontFamily: MONO,
                fontSize: 23,
              }}
            >
              <span style={{color: C.faint}}>https://</span>
              <span style={{color: C.ink}}>{url.slice(0, typed)}</span>
              <span style={{opacity: caret && typed < url.length ? 1 : 0, color: C.signal}}>|</span>
            </div>
            <div
              style={{
                ...useRise(30, 14),
                alignSelf: "flex-start",
                fontFamily: MONO,
                fontSize: 22,
                color: C.ground,
                background: C.signal,
                borderRadius: 10,
                padding: "12px 22px",
                fontWeight: 700,
              }}
            >
              Draft ▸
            </div>
          </div>
          {/* Arrow */}
          <div style={{display: "flex", alignItems: "center", opacity: arrow}}>
            <div style={{width: interpolate(arrow, [0, 1], [0, 56]), height: 3, background: C.signal}} />
            <div
              style={{
                width: 0,
                height: 0,
                borderTop: "9px solid transparent",
                borderBottom: "9px solid transparent",
                borderLeft: `15px solid ${C.signal}`,
              }}
            />
          </div>
          {/* Generated OKF article */}
          <div
            style={{
              ...useRise(46, 24),
              width: 720,
              background: C.panel,
              border: `1px solid ${C.hair}`,
              borderRadius: 16,
              padding: "24px 28px",
              position: "relative",
            }}
          >
            <div style={{position: "absolute", top: 16, right: 20, fontFamily: MONO, fontSize: 15, letterSpacing: 2, textTransform: "uppercase", color: C.faint}}>
              rollout-feature-flags.md
            </div>
            <StudioLine frame={frame} delay={54} segs={[dim("---")]} />
            <StudioLine frame={frame} delay={62} segs={[key("type: "), val("Guide")]} />
            <StudioLine frame={frame} delay={70} segs={[key("title: "), val("Rolling out feature flags safely")]} />
            <StudioLine frame={frame} delay={80} segs={[key("domain: "), val("finserv-ai")]} />
            <StudioLine frame={frame} delay={88} segs={[key("tags: "), val("[flags, release, safety]")]} />
            <StudioLine frame={frame} delay={96} segs={[dim("---")]} />
            <StudioLine frame={frame} delay={110} segs={[{t: "# Rolling out feature flags safely", c: C.ink}]} />
            <StudioLine frame={frame} delay={124} segs={[val("Ship behind a flag, release to 1%, then")]} />
            <StudioLine frame={frame} delay={132} segs={[val("widen — see the "), wl("[[Release checklist]]"), val(" first.")]} />
            {/* Callouts, kept outside the card edges so they never sit over the text. */}
            <div style={{...rev(frame, 150, 8), position: "absolute", left: -4, top: 44, fontFamily: MONO, fontSize: 15, color: C.signalInk, background: `${C.signal}18`, border: `1px solid ${C.signal}55`, borderRadius: 6, padding: "3px 8px", transform: "translateX(-100%)"}}>
              frontmatter
            </div>
            <div style={{...rev(frame, 158, 8), position: "absolute", left: -4, bottom: 46, fontFamily: MONO, fontSize: 15, color: C.steel, background: `${C.steel}18`, border: `1px solid ${C.steel}66`, borderRadius: 6, padding: "3px 8px", transform: "translateX(-100%)"}}>
              wikilink
            </div>
          </div>
        </div>
        <H1 size={60} style={{...useRise(176, 20)}}>
          Studio drafts the structure. You just finalise.
        </H1>
      </div>
    </Scene>
  );
};

// ---------------------------------------------------------------- 8. Open Knowledge Format
export const SceneOKF: React.FC = () => {
  const frame = useCurrentFrame();
  const parts = ["Markdown", "YAML frontmatter", "[[wikilinks]]", "Git"];
  return (
    <Scene>
      <div style={{display: "flex", flexDirection: "column", alignItems: "center", gap: 40}}>
        <Eyebrow delay={4}>Open, not locked in</Eyebrow>
        <div style={{display: "flex", alignItems: "center", gap: 18, flexWrap: "wrap", justifyContent: "center", maxWidth: 1500}}>
          {parts.map((p, i) => (
            <React.Fragment key={p}>
              <div style={rev(frame, 10 + i * 10, 18)}>
                <Pill accent={i === 2 ? C.steel : C.signal} style={{fontSize: 28, padding: "16px 26px"}}>
                  {p}
                </Pill>
              </div>
              {i < parts.length - 1 && (
                <div style={{...rev(frame, 16 + i * 10, 0), fontFamily: SANS, fontSize: 46, color: C.faint}}>+</div>
              )}
            </React.Fragment>
          ))}
          <div style={{...rev(frame, 56, 0), fontFamily: SANS, fontSize: 46, color: C.signal}}>=</div>
          <div style={rev(frame, 62, 18)}>
            <Pill accent={C.signal} style={{fontSize: 28, padding: "16px 26px", background: `${C.signal}22`, fontWeight: 700}}>
              Portable knowledge
            </Pill>
          </div>
        </div>
        <H1 size={66} style={{...useRise(76, 22)}}>
          The Open Knowledge Format — diffable, portable, yours.
        </H1>
        <div style={{...useRise(96, 14), fontFamily: MONO, fontSize: 23, color: C.muted}}>
          Plain files in git. Export the whole bundle any time.
        </div>
      </div>
    </Scene>
  );
};

// ---------------------------------------------------------------- 9. No installs / in-tenant GCP
export const SceneTenant: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const pop = spring({frame: frame - 8, fps, config: {damping: 130}});
  return (
    <Scene>
      <div style={{display: "flex", flexDirection: "column", alignItems: "center", gap: 38}}>
        <Eyebrow delay={4}>Nothing to install</Eyebrow>
        {/* Browser-in-tenancy mock. marginTop clears the absolutely-positioned tenancy
            label above the dashed boundary from colliding with the eyebrow. */}
        <div style={{position: "relative", marginTop: 40, transform: `scale(${interpolate(pop, [0, 1], [0.9, 1])})`, opacity: pop}}>
          {/* Tenancy boundary */}
          <div
            style={{
              position: "absolute",
              inset: -28,
              border: `2px dashed ${C.signal}66`,
              borderRadius: 22,
            }}
          />
          <div
            style={{
              position: "absolute",
              top: -30,
              left: 20,
              transform: "translateY(-100%)",
              fontFamily: MONO,
              fontSize: 18,
              letterSpacing: 2,
              textTransform: "uppercase",
              color: C.signalInk,
            }}
          >
            Your Google Cloud project
          </div>
          {/* Browser */}
          <div style={{width: 760, background: C.panel, border: `1px solid ${C.hair}`, borderRadius: 14, overflow: "hidden"}}>
            <div style={{display: "flex", alignItems: "center", gap: 10, padding: "14px 18px", borderBottom: `1px solid ${C.hair}`}}>
              <div style={{width: 12, height: 12, borderRadius: 99, background: "#c1543f"}} />
              <div style={{width: 12, height: 12, borderRadius: 99, background: "#d1a23a"}} />
              <div style={{width: 12, height: 12, borderRadius: 99, background: "#5a8f5a"}} />
              <div style={{marginLeft: 14, flex: 1, background: C.panel2, borderRadius: 8, padding: "8px 14px", fontFamily: MONO, fontSize: 18, color: C.muted}}>
                brain.your-company.internal
              </div>
            </div>
            <div style={{padding: 30, display: "flex", alignItems: "center", gap: 20}}>
              <Glyph size={64} />
              <div>
                <div style={{fontFamily: SANS, fontWeight: 800, fontSize: 34, color: C.ink}}>Hyper Brain</div>
                <div style={{fontFamily: MONO, fontSize: 17, color: C.muted, letterSpacing: 1}}>runs in the browser · nothing to download</div>
              </div>
            </div>
          </div>
        </div>
        <div style={{display: "flex", gap: 16, flexWrap: "wrap", justifyContent: "center"}}>
          {[
            {t: "Scale-to-zero", a: C.signal},
            {t: "In-tenancy", a: C.steel},
            {t: "OAuth 2.1 · MCP", a: C.signal},
          ].map((p, i) => (
            <div key={p.t} style={useRise(40 + i * 8, 18)}>
              <Pill accent={p.a} style={{fontSize: 24}}>{p.t}</Pill>
            </div>
          ))}
        </div>
        <H1 size={58} style={{...useRise(66, 20)}}>
          No plugins. No downloads. Your data never leaves your project.
        </H1>
      </div>
    </Scene>
  );
};

// ---------------------------------------------------------------- 10. Agent team
export const SceneAgents: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const chain = ["You", "Coordinator", "Researcher", "Brain"];
  const gapX = 300;
  const startX = 130;
  const y = 90;
  const seg = (frame % 90) / 90;
  const total = chain.length - 1;
  const segIdx = Math.min(total - 1, Math.floor(seg * total));
  const local = seg * total - segIdx;
  const px = startX + (segIdx + local) * gapX;
  return (
    <Scene>
      <div style={{display: "flex", flexDirection: "column", alignItems: "center", gap: 46}}>
        <Eyebrow delay={4}>Agent team</Eyebrow>
        <svg width={1120} height={200} viewBox="0 0 1120 200">
          {chain.slice(0, -1).map((_, i) => (
            <line
              key={i}
              x1={startX + i * gapX + 60}
              y1={y}
              x2={startX + (i + 1) * gapX - 60}
              y2={y}
              stroke={C.hair}
              strokeWidth={2}
            />
          ))}
          {frame > 20 && <circle cx={px} cy={y} r={9} fill={C.signal} />}
          {chain.map((label, i) => {
            const p = spring({frame: frame - (10 + i * 8), fps, config: {damping: 130}});
            const cx = startX + i * gapX;
            const isBrain = label === "Brain";
            return (
              <g key={label} transform={`translate(${cx}, ${y})`} opacity={p}>
                <circle r={54} fill={C.panel} stroke={isBrain ? C.signal : C.hair} strokeWidth={2} />
                <circle r={54} fill={isBrain ? C.signal : "transparent"} fillOpacity={0.08} />
                <text textAnchor="middle" dy={7} fontFamily={MONO} fontSize={19} fill={isBrain ? C.signalInk : C.ink}>
                  {label}
                </text>
              </g>
            );
          })}
        </svg>
        <div style={{...useRise(40, 14), fontFamily: MONO, fontSize: 22, color: C.muted, letterSpacing: 1}}>
          transfer_to_agent() · search over authenticated MCP
        </div>
        <H1 size={66} style={{...useRise(52, 22)}}>
          A real agent team, working inside your walls.
        </H1>
      </div>
    </Scene>
  );
};

// ---------------------------------------------------------------- 11. Outro
export const SceneOutro: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const pop = spring({frame, fps, config: {damping: 140, mass: 0.8}});
  return (
    <Scene>
      <div style={{display: "flex", flexDirection: "column", alignItems: "center", gap: 34}}>
        <div style={{display: "flex", alignItems: "center", gap: 26, transform: `scale(${interpolate(pop, [0, 1], [0.8, 1])})`, opacity: pop}}>
          <Glyph size={96} />
          <div style={{fontFamily: SANS, fontWeight: 800, fontSize: 96, letterSpacing: -3, color: C.ink}}>
            Hyper Brain
          </div>
        </div>
        <div style={{...useRise(16, 20), fontFamily: SANS, fontSize: 44, color: C.muted, textAlign: "center"}}>
          Your company&apos;s shared memory.
        </div>
        <div
          style={{
            ...useRise(30, 16),
            marginTop: 10,
            display: "flex",
            gap: 16,
            fontFamily: MONO,
            fontSize: 24,
            color: C.signalInk,
          }}
        >
          <span style={{padding: "12px 22px", borderRadius: 999, background: `${C.signal}18`, border: `1px solid ${C.signal}55`}}>
            Sign in with Google
          </span>
          <span style={{padding: "12px 22px", borderRadius: 999, border: `1px solid ${C.hair}`, color: C.muted}}>
            or continue as guest
          </span>
        </div>
      </div>
    </Scene>
  );
};
