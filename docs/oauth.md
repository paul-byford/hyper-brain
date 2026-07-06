# Remote connectors (OAuth)

Hyper Brain ships an **in-tenancy OAuth 2.1 Authorization Server** so people can add
the brain to Claude or ChatGPT as a **custom / remote connector** just by pasting
its URL. No third party sees your users or their prompts: sign-in is brokered to
Google, tokens are signed by a key in your own Secret Manager, and the brain
validates them itself.

## How it works

```
Claude / ChatGPT  ──add URL──▶  brain /mcp   (401 + WWW-Authenticate)
        │                          │  points at the AS
        ├─ discover ──▶  auth service /.well-known/oauth-authorization-server
        ├─ register (DCR) ─▶  /register            (client_id = a signed JWT)
        ├─ authorize ─────▶  /authorize ─▶ Google sign-in ─▶ /oauth2/callback
        └─ token ─────────▶  /token                (access + refresh tokens)
                                   │
brain (resource server) ◀──Bearer access token──┘   validates via the AS JWKS,
   maps the Google email to the domain policy, scopes every read/write.
```

The AS is **stateless** (every artefact is a signed JWT), so it runs on the same
scale-to-zero Cloud Run as everything else, with no datastore. The brain keeps
accepting the ADK agent's Google ID tokens too (`BRAIN_AUTH=composite`).

## Security posture change

To let a hosted client (Anthropic's / OpenAI's servers) reach `/mcp`, the brain's
Cloud Run edge is opened to `allUsers` on the **personal** profile once OAuth is
live. The OAuth bearer becomes the sole gate (verified in-app). The **controlled**
profile stays perimeter-internal and is unaffected. If you don't want this, set
`enable_oauth = false` in your tfvars.

## Enabling it (one-time)

OAuth needs a Google OAuth client whose redirect URI is the AS's callback, and
that URL isn't known until the service exists -- so bring-up is two passes with a
console step between.

1. **Deploy once** to create the services and learn the URLs:
   ```
   ./brain up            # Windows: .\brain.ps1 up
   ```
   Note the printed `auth:` and `brain:` URLs (also `terraform -chdir=infra output`).

2. **Create the Google OAuth client** (one time, in the Cloud Console):
   - APIs & Services → **OAuth consent screen**: External; add your Google account
     as a **test user**; scopes `openid` and `email` are enough.
   - APIs & Services → **Credentials** → Create credentials → **OAuth client ID** →
     **Web application**.
   - **Authorized redirect URI**: `<auth_url>/oauth2/callback`
     (e.g. `https://brain-auth-xxxx-nw.a.run.app/oauth2/callback`).
   - Copy the **Client ID** and **Client secret**.

3. **Add the credentials** to `config/personal.tfvars` (git-ignored):
   ```hcl
   google_client_id     = "…apps.googleusercontent.com"
   google_client_secret = "…"
   ```

4. **Deploy again**: the AS goes live and the brain opens to remote connectors:
   ```
   ./brain up
   ```

5. **Grant yourself** so you actually see content. Your identity is your bare
   Google **email**. Add it to `extra_grants` in `config/personal.tfvars`
   (git-ignored, so your email is never committed), then re-apply:
   ```hcl
   extra_grants = [
     { principal = "you@example.com", domains = ["finserv-ai-engineering", "enterprise-ai-recruitment"], write = true },
   ]
   ```
   ```
   ./brain up
   ```
   Terraform merges this into the published policy (the tracked `config/*.policy.yaml`
   stays `@example.com`); the brain reloads it within ~30s.

## Testing with Claude

Claude's custom connectors accept general MCP servers, so this is the smooth path.

1. Claude.ai → **Settings → Connectors → Add custom connector** (Pro/Max/Team/
   Enterprise; also in Claude Desktop's Connectors).
2. **URL**: `<brain_url>/mcp`
3. Claude discovers the AS, opens a browser to **Sign in with Google**; approve the
   consent screen. Claude stores the token and refreshes it automatically.
4. In a chat, the brain's tools (`search`, `answer`, `list_domains`,
   `get_document`, `propose_document`) are available; ask it to search Hyper Brain.

No manual token, no hourly refresh, which is the whole point of OAuth.

## Testing with ChatGPT

ChatGPT can add remote MCP servers as connectors and will run the same OAuth flow
(URL → discover → Google sign-in → token).

- **Settings → Connectors → Add** (availability depends on your plan / developer
  mode) → **URL** `<brain_url>/mcp` → complete the Google sign-in.
- **Caveat:** ChatGPT's *Deep Research* connectors expect the server to expose
  `search` and `fetch` tools with a specific shape. Hyper Brain exposes `search`
  plus `get_document` (not `fetch`), so it connects as a general tool provider but
  may not slot into Deep Research without a small tool-name/shape adapter. Claude
  is the less constrained client for a first test.

## Troubleshooting

- **Connector can't reach the server / 401 loops:** confirm `enable_oauth = true`,
  the Google creds are set, and you ran `./brain up` a second time. Check the AS is
  serving: `curl <auth_url>/.well-known/oauth-authorization-server`.
- **Signed in but "no domains":** your Google email isn't granted in the bucket
  policy (see step 5).
- **`redirect_uri_mismatch` from Google:** the OAuth client's Authorized redirect
  URI must be exactly `<auth_url>/oauth2/callback`.
- **Disable everything:** `enable_oauth = false` in tfvars + `./brain up` returns
  the brain to Google-identity-only, IAM-gated.
