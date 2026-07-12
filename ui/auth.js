// Browser OAuth 2.1 (PKCE) against the in-tenancy Authorization Server. Public
// client, no secret: we register once (DCR), redirect to the AS to sign in with
// Google, then exchange the returned code for an access token. The token lives in
// sessionStorage for the tab's life only. Everything here is vanilla fetch/crypto.

const CLIENT_KEY = "hb_client_id";
const VERIFIER_KEY = "hb_pkce_verifier";
const STATE_KEY = "hb_oauth_state";
const TOKEN_KEY = "hb_access_token";

const b64url = (bytes) =>
  btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

function randomString(n = 48) {
  const a = new Uint8Array(n);
  crypto.getRandomValues(a);
  return b64url(a);
}

async function s256(verifier) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return b64url(digest);
}

const redirectUri = () => window.location.origin + window.location.pathname;

// Dynamic client registration (RFC 7591), cached so we register at most once.
async function clientId(authUrl) {
  const cached = localStorage.getItem(CLIENT_KEY);
  if (cached) return cached;
  const resp = await fetch(`${authUrl}/register`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      client_name: "Hyper Brain Explorer",
      redirect_uris: [redirectUri()],
      token_endpoint_auth_method: "none",
      grant_types: ["authorization_code", "refresh_token"],
      response_types: ["code"],
    }),
  });
  if (!resp.ok) throw new Error(`client registration failed (${resp.status})`);
  const id = (await resp.json()).client_id;
  localStorage.setItem(CLIENT_KEY, id);
  return id;
}

export function token() {
  return sessionStorage.getItem(TOKEN_KEY) || null;
}

export function signOut() {
  sessionStorage.removeItem(TOKEN_KEY);
}

// Guest access: fetch a read-only token the AS mints with no Google login, and store it
// exactly like a real one. The brain maps it to a guest identity that can browse but
// never write, so the whole app opens with a single click for a frictionless demo.
export async function guestLogin(authUrl) {
  const resp = await fetch(`${authUrl}/guest`);
  if (!resp.ok) throw new Error(`guest access failed (${resp.status})`);
  const access = (await resp.json()).access_token;
  sessionStorage.setItem(TOKEN_KEY, access);
  return access;
}

// Kick off the redirect to the AS. Returns a promise that never resolves (navigates).
export async function beginLogin(authUrl) {
  const verifier = randomString();
  const state = randomString(16);
  sessionStorage.setItem(VERIFIER_KEY, verifier);
  sessionStorage.setItem(STATE_KEY, state);
  const params = new URLSearchParams({
    response_type: "code",
    client_id: await clientId(authUrl),
    redirect_uri: redirectUri(),
    code_challenge: await s256(verifier),
    code_challenge_method: "S256",
    state,
    scope: "mcp",
  });
  window.location.assign(`${authUrl}/authorize?${params.toString()}`);
}

// If we came back from the AS with ?code, exchange it for a token. Returns the token
// on success, null if there was no code to handle. Cleans the URL either way.
export async function completeLoginIfRedirected(authUrl) {
  const url = new URL(window.location.href);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  if (!code) return null;

  const clean = () => window.history.replaceState({}, document.title, redirectUri());
  const expected = sessionStorage.getItem(STATE_KEY);
  const verifier = sessionStorage.getItem(VERIFIER_KEY);
  if (!state || state !== expected || !verifier) { clean(); throw new Error("sign-in state mismatch"); }

  const resp = await fetch(`${authUrl}/token`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      code,
      redirect_uri: redirectUri(),
      client_id: await clientId(authUrl),
      code_verifier: verifier,
    }),
  });
  sessionStorage.removeItem(VERIFIER_KEY);
  sessionStorage.removeItem(STATE_KEY);
  clean();
  if (!resp.ok) throw new Error(`token exchange failed (${resp.status})`);
  const access = (await resp.json()).access_token;
  sessionStorage.setItem(TOKEN_KEY, access);
  return access;
}
