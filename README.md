# AI powered Advertisement generator to run any campaign within minutes

A customer's brand plus
a request goes in, an AI agent generates an on-brand ad, a human iterates on
it via pinned comments, and a second AI agent deploys the final ad into a
stand-in ad platform ("Adstream") using a real browser.

Every unit of agent work — generate, edit, deploy — follows the same shape:
a clean sandbox spins up, the right files get hydrated into it, the agent
works and uploads its own output from inside the box, then the box is
destroyed. Nothing durable ever lives only inside a sandbox; a fresh box
rehydrated from storage can always continue as if the old one never existed.
See `docs/ROADMAP.md` for the full design.

## Layout

| Path | What it is |
|---|---|
| `frontend/` | Next.js app — request intake, comment/feedback UI, deploy trigger. |
| `worker/orchestrator/` | Dispatcher that claims queued runs/deploys and enforces concurrency caps. |
| `worker/hydration/` | Pure functions that assemble the files a sandbox needs, fresh, from Postgres/Storage. |
| `worker/sandbox_images/` | The agent-facing side: the skill, tools, and runner scripts that actually run inside a sandbox. |
| `supabase/` | Schema migrations, tenant onboarding, and seed scripts. |
| `design-brains/`, `design-brains-test/` | Brand specs (`DESIGN.md`, tokens, fonts, assets) the pipeline was built and tested against. |
| `inspirations/` | Reference-only creative examples per brand (never a source of color/type/copy). |
| `starter/` | Example request payloads in this project's request shape. |
| `outputs_generated/` | Real runs of the pipeline — generated ads, agent transcripts, and results, kept as evidence of behavior. |
| `scripts/` | Local preflight tooling (env/credential checks) — never touches billable resources. |
| `docs/` | Planning docs, decisions, and findings from building this (see `docs/README.md`). |

## Running it

1. `cp .env.example .env` and fill in real credentials (Anthropic, OpenAI,
   E2B, Kernel, Supabase, Adstream — see the comments in `.env.example` for
   exactly which sandbox each key is allowed into).
2. `cd scripts && python -m venv .venv && .venv/Scripts/activate && pip install -r requirements.txt && python check_env.py`
   to confirm every credential actually works before spinning up anything
   billable.
3. Apply the schema in `supabase/migrations/` (in order) to a Supabase
   project, then run `supabase/seed/seed.py` to load the Emplifi/Kahua/Oatly
   design brains as tenants.
4. `cd worker/orchestrator && pip install -r requirements.txt && python dispatcher.py`
   to start the worker that claims queued runs and deploys.
5. `cd frontend && npm install && npm run dev` for the request/comment/deploy UI.

## Docs

Start with `docs/ROADMAP.md` (architecture), then `SKILL.md` (the agent's
actual product spec) and `docs/BUILD_GUIDE.md` (the ordered build plan). See
`docs/README.md` for the full index — including `docs/DECISIONS.md`,
`docs/FLOW.md`, and `docs/FINDINGS.md`.


## A few generated Advertisements:


![Project Screenshot](outputs_generated\emplifi\2026-gartner-leader-3844daae\2026-gartner-leader-3844daae\revisions\1\story\render.png)

![Project Screenshot](outputs_generated\kahua\noaai-d47fde22\noaai-d47fde22\revisions\1\square\render.png)


