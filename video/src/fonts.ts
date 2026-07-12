// The app uses Inter Tight + JetBrains Mono. Inter (the closest Google Fonts sibling) and
// JetBrains Mono are pulled in via Remotion's font loader so they embed at render time.
import {loadFont as loadInter} from "@remotion/google-fonts/Inter";
import {loadFont as loadMono} from "@remotion/google-fonts/JetBrainsMono";

export const SANS = loadInter().fontFamily;
export const MONO = loadMono().fontFamily;
