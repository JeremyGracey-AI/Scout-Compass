# Deploy runbook — Scout Compass web app

The web app (`web/app.py` + `web/templates/index.html`) is a stateless renderer: it
generates skills/automations from a posted persona and **stores nothing**. Accounts and the
persona library are handled in the browser directly against Supabase (row-level security),
so the server never holds user data or secrets.

## Architecture

```
Browser ──(persona JSON)──▶ Flask /api/generate ──▶ rendered SKILL.md + automations (no-store)
   │
   └──(magic-link auth + library CRUD)──▶ Supabase (Postgres + Auth, RLS per user)
```

## 1. Supabase (already provisioned)

- Project: `doghouse-bubbles` (`ivysnobxweftdmvfevqj`), region `us-east-1`.
- Table: `public.skillforge_personas` with RLS — each row is readable/writable only by its
  owner (`auth.uid() = user_id`, default `user_id = auth.uid()`). (The table keeps its
  original name after the Scout Compass rebrand, so the live deployment and saved personas
  keep working without a data migration.)
- Frontend config (public, RLS-gated):
  - `SUPABASE_URL = https://ivysnobxweftdmvfevqj.supabase.co`
  - `SUPABASE_ANON_KEY = sb_publishable_...` (publishable key)

### Required dashboard step — magic-link redirect URLs

Magic-link sign-in redirects back to your app, so the app URL must be allow-listed:

1. Supabase dashboard → **Authentication → URL Configuration**.
2. Set **Site URL** to your deployed origin (e.g. `https://<your-app>.vercel.app`).
3. Add redirect URLs: `http://localhost:5000` (local dev) and your Vercel URL.

`localhost` works out of the box, so local dev needs no change.

## 2. Run locally

```bash
pip install -e ".[web]"
cp web/.env.example web/.env     # already created locally with the demo project's values
python web/app.py                # http://127.0.0.1:5000
```

Sign in with your email → check inbox for the link → "My executives" appears.

## 3. Deploy to Vercel

The repo is deploy-ready: `vercel.json` (Python build + `includeFiles` for templates and
personas) and `api/index.py` (exposes the Flask WSGI app). The serverless entry sets the
demo Supabase config via `os.environ.setdefault`, so a bare deploy works; real env vars
override it.

From the project root, with the Vercel CLI authenticated as you:

```bash
npm i -g vercel        # if needed
vercel deploy          # first run links/creates the project
vercel deploy --prod   # production deploy
```

Or connect the repo to Vercel's Git integration and push — every push deploys.

Recommended on Vercel (Project → Settings → Environment Variables), instead of the baked
demo values:

```
SUPABASE_URL=https://<your-project>.supabase.co
SUPABASE_ANON_KEY=sb_publishable_<your-key>
```

After the first deploy, copy the `*.vercel.app` URL into the Supabase Auth URL config (step 1).

## 4. Verify

- `GET /` returns the app shell (verified in CI via the web smoke test).
- `POST /api/generate` returns skills + automations for an inline persona.
- Sign in → save an executive → reload → it persists (proves RLS + auth).

## 5. Later: migrating to Azure (for the Microsoft motion)

The core is portable — only the two edges change:

- **Auth:** swap Supabase magic-link for **Microsoft Entra ID** (MSAL). The Scout audience
  already has M365 accounts; register an app in your tenant and replace the Supabase auth
  calls in `index.html` with MSAL.js. The library API contract (list/save/delete by user)
  stays the same.
- **Storage:** move `skillforge_personas` to **Azure Database for PostgreSQL** (or Cosmos DB)
  and enforce per-user access in a thin API (Entra-validated JWT) instead of Supabase RLS.
- **Hosting:** Flask runs on **Azure App Service** or **Container Apps**; `vercel.json` is
  replaced by an App Service config or a Dockerfile. The generator (`cli/`, `templates/`) is
  unchanged.

Keep generation server-side and no-store in both stacks so persona data is never persisted by
the renderer.
