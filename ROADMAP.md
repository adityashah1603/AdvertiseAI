# ROADMAP.md — Build Context for the Coding Agent

You are building **the design engine**: a small but real version of CharacterQuilt's
product. A customer's brand + a request goes in; an AI agent generates an on-brand
ad, a human iterates on it via pinned comments, and a second AI agent deploys the
final ad into a stand-in ad platform ("Adstream") using a real browser.

Read this entire file before writing code. Read `SKILL.md` and both
`design-brains/design-brains/*/DESIGN.md` files next. They are the actual product
spec; this file is the engineering plan on top of them.

---

## 0. The one idea everything must obey

> Everything is a file system. Files and skills, hydrated in different orders at
> different times.

Every unit of agent work — generating an ad, editing an ad, deploying an ad — is
the same event:

```
clean sandbox spins up
  → the right files get written into it
  → the agent gets a prompt
  → the agent works
  → the agent saves its own output somewhere durable (outside the box)
  → the box is destroyed
```

Nothing durable is allowed to live only inside a sandbox. If a box is killed at any
point, a new box rehydrated from storage must be able to continue as if the old
box had never existed. **If a design decision doesn't fit this shape, it's wrong —
redesign it, don't special-case around it.**

Three kinds of data feed a box. Keep them structurally separate everywhere
(storage layout, code, prompts) — never let them blur into one bucket of "stuff
the box needs":

| Tier | Examples | Changes how often |
|---|---|---|
| **Global** | `SKILL.md`, prompt templates, rendering tooling | Same for every run, every tenant |
| **Tenant (brand)** | `DESIGN.md`, fonts, asset manifest, tokens | Same for one customer, across all their jobs |
| **Job** | The request, its copy, its comments, its revision history | Unique to one task, changes every run |

A rebrand (tenant tier changes) must never require touching code or redeploying
anything (job or global tier).

---

## 1. Hard disqualifiers — never do these

Any one of these is an automatic failure, regardless of how good the rest is.
Treat this list as harder than any other requirement in this document.

1. **Nothing but the agent moves work out of a sandbox.** No backend process that
   reaches into a sandbox's filesystem after the run, polls its disk, or
   "collects" an out-directory. The agent uploads its own results, from inside
   the box, before the box dies.
2. **No tenant- or task-specific sandbox identity.** No "Kahua box" and "Emplifi
   box." A sandbox's image, template, name, or id must never encode which
   customer or task it's serving. Brand data is fetched fresh, at runtime, using
   the tenant id carried in that run's job data — never baked in, never assumed
   from a prior run on the "same" box (there is no same box).
3. **The agent never runs as a subprocess of the backend.** No spawning `claude`
   next to your API process. It runs inside an actual isolated sandbox
   (E2B), reached only through the sandbox provider's API. A queue in front of it
   is fine; co-location with the backend is not.
4. **No agent ever runs on a developer laptop.** Especially not the deployment
   agent.
5. **No work exists only on a box.** If a box is killed mid-task, the system must
   recover from durable storage, not from anything that lived only on that box.
6. **No hardcoded ordering.** The system must not require requests to arrive in
   any particular sequence. Build and test for arbitrary interleavings.

Also disallowed as scope (explicitly called out as time sinks, not requirements):
brand-kit versioning/rollback UI, a "brand conformance grader" (any automated
score of whether an ad "looks on-brand" — a human/agent looking at the PNG is the
only allowed judge of that), a classifier that decides whether a comment needs a
text edit vs a full regeneration (let the agent decide), a custom scheduler
(a capped concurrent-run counter + FIFO queue is enough), a permission system
for what the agent's credentials can reach, and any performance optimization.

---

## 2. Locked technical decisions

| Decision | Choice | Why |
|---|---|---|
| Frontend | Next.js (React) | Matches the brief's own stack; server actions/route handlers double as the backend API layer if desired |
| Backend / workers | Python | Orchestration, sandbox hydration, agent invocation, rendering pipeline |
| Database + storage | Supabase (Postgres + Storage buckets) | One system for durable job state (Postgres rows) and durable file artifacts (Storage) — both survive any sandbox dying |
| Agent runtime | Claude Agent SDK / `claude -p` (headless) | Runs *inside* the sandbox, not on the host |
| Sandbox provider | E2B | Plain sandbox provider (not a managed-agent platform); scriptable filesystem + process API fits the hydrate/destroy model directly |
| Image generation | `gpt-image-2` via OpenAI Images API | Required by the brief |
| Feedback surface | Pinned comments (area, not point) | Chosen over chat to demonstrate the region/revision/coordinate hydration the brief grades hardest |
| Deployment browser | Kernel (managed browser + session recording API) | Matches what CharacterQuilt actually uses; gives recording "for free" instead of wiring Playwright's own video capture |
| Sandbox images | **Two**: `generation` (fonts, image-render tooling, OpenAI key) and `deployment` (browser via Kernel, Adstream credential) | They need disjoint tools and disjoint credentials; one fat image widens each run's blast radius for no benefit |

Read all secrets (OpenAI key, Supabase service key, E2B key, Kernel key, Adstream
credential) from environment variables. Never commit them. Each sandbox type gets
only the secrets it needs — the generation box never sees the Adstream login; the
deployment box never sees the OpenAI key.

---

## 3. Data model

### 3.1 Postgres tables (Supabase)

Keep this minimal — it exists to make runs resumable and auditable, not to be a
general CMS.

- **`tenants`** — `id`, `slug`, `name`, `brand_kit_storage_prefix`. One row per
  customer (Kahua, Emplifi, and whatever third brand shows up later). Nothing
  else in the schema may reference a tenant by name — only by `id`/foreign key.
- **`requests`** (a "task") — `id`, `tenant_id`, `kind` (`new`/`edit`), `campaign`,
  `copy` (jsonb), `canvases` (jsonb), `inspirations` (text[] of filenames),
  `parent_request_id` (nullable, for edits), `created_by`, `created_at`.
- **`revisions`** — `id`, `request_id`, `revision_number`, `status`
  (`pending`/`generating`/`ready`/`failed`), `run_id` (fk), `created_at`. Each
  successful generation or edit produces a new revision; nothing is overwritten
  in place.
- **`assets`** — `id`, `revision_id`, `canvas_name`, `width`, `height`,
  `plate_path`, `html_path`, `png_path` (all Storage paths). One row per canvas
  size per revision.
- **`comments`** — `id`, `request_id`, `revision_id` (the revision it was left
  on), `canvas_name`, `region` (jsonb: `x,y,width,height`), `body`, `author`,
  `status` (`open`/`resolved`/`stale`/`orphaned`), `created_at`.
- **`runs`** — `id`, `type` (`generate`/`edit`/`deploy`), `tenant_id`,
  `request_id`, `revision_id` (nullable until it produces one), `status`
  (`queued`/`running`/`succeeded`/`failed`/`crashed`), `sandbox_id` (opaque,
  provider-issued — never a human-readable tenant/task name), `error_message`,
  `transcript_path`, `started_at`, `ended_at`.
- **`deploys`** — `id`, `revision_id`, `run_id`, `adstream_ad_name`,
  `adstream_url`, `verified` (bool), `recording_path`, `status`.

Every row that represents job state is reconstructible purely from Postgres +
Storage. No table may hold a foreign key into "the current sandbox" — sandboxes
are transient and disposable by design.

### 3.2 Storage layout (Supabase Storage buckets)

**Revised from the original shared-bucket design**: `brand-kit` and `jobs`
are each **one Storage bucket per tenant**, created at onboarding time by
`supabase/onboarding.py`'s `onboard_tenant()` — not a shared bucket with a
`{tenant_id}/` path prefix. Reasoning: a bug in one tenant's bucket/policy
setup then stays contained to that one bucket, instead of a single shared
policy mistake exposing every tenant at once. `inspirations/` and
`deploys/` below still use the older shared-prefix pattern and haven't been
revisited under the same lens yet — worth doing before either matters for
real (inspirations once request-attached selection is built; deploys in
Step 7).

```
skill/                                   # global tier - baked into the sandbox
  SKILL.md                                # image/template itself, not fetched
  prompts/...                             # from Storage per run (see §4.1)
  render-tooling/...

brand-kit-{tenant_id}/                   # ONE BUCKET PER TENANT - fetched fresh every run
  DESIGN.md
  fonts/...
  brand/asset_manifest.json
  brand/tokens.json

jobs-{tenant_id}/                        # ONE BUCKET PER TENANT, separate from brand-kit -
  {request_id}/revisions/{n}/             # different access pattern (write-heavy, agent-authored
    request.json                          # via a per-run signed URL) from brand-kit's read-heavy,
    comments.json                         # orchestrator-only access
    assets/{canvas_name}.plate.png
    assets/{canvas_name}.png              # final rendered composite
    html/{canvas_name}.html
    RESULT.json
    agent-transcript.jsonl                # full raw transcript, saved every run

inspirations/{tenant_id}/                # tenant tier, but request-selected - still shared-prefix
  {filename}.png

deploys/{request_id}/revisions/{n}/      # still shared-prefix
  recording.mp4
  detail-page-snapshot.png
```

This layout *is* the hydration/resume mechanism: rehydrating revision 3 for a
retry after revision 4 failed means reading `jobs-{tenant_id}/{request_id}/revisions/3/`
and `brand-kit-{tenant_id}/` fresh into a brand-new sandbox — nothing
sandbox-specific is ever required. Prefer this **recipe-replay** approach (a pure
function `hydrate(tenant_id, request_id, revision_number) -> sandbox files`) over
snapshotting whole sandboxes: it's provider-agnostic and makes the "kill the box,
spin a new one, rehydrate" test trivially satisfiable by construction.

---

## 4. Hydration contract, in detail

### 4.1 A generation/edit run

1. Backend inserts a `requests` row (or a new `revisions` row for an edit) and a
   `runs` row with `status='queued'`.
2. An orchestrator (respecting the concurrency cap, §5) claims the next queued
   run and opens a fresh E2B sandbox with a random/opaque id.
3. Orchestrator writes into the sandbox, using only the run's `tenant_id` and
   `request_id`/`revision_number` — never a cached "current" tenant:
   - global: skill files, prompt templates, rendering tooling (may be baked into
     the sandbox template — this is fine, it carries no tenant/task identity)
   - tenant: that tenant's `DESIGN.md`, `fonts/`, `asset_manifest.json`,
     `tokens.json`, pulled fresh from that tenant's own `brand-kit-{tenant_id}`
     bucket (looked up via `tenants.brand_kit_bucket`, never re-derived or
     assumed)
   - job: `request.json`, the copy, the selected inspiration file(s) (only the
     ones the request names — never the whole `inspirations/` folder), and, for
     an edit, the prior revision's assets plus any `open` comments with their
     region coordinates
   - a generated task prompt referencing everything above by its local sandbox
     path
4. Agent runs headless inside the box (image generation via OpenAI, HTML overlay
   authoring, canvas rendering to PNG, then the agent **looks at its own
   rendered PNG** and self-critiques before finishing — this step is mandatory,
   not optional polish).
5. **The agent itself** writes `RESULT.json` and all produced assets back to
   `{request_id}/revisions/{n}/` inside that tenant's own `jobs-{tenant_id}`
   bucket, using a per-run signed upload URL scoped to that exact path
   (minted by the orchestrator before hydration, never a standing key),
   before it exits.
6. The agent (or a supervisor process watching the run, but never one that reads
   the sandbox's own filesystem) confirms the upload landed by checking Storage,
   then flips the `runs`/`revisions` rows to `succeeded`. The sandbox is
   destroyed immediately after.
7. **Failure must be loud and legible to the agent, in the same run.** If a save
   fails, the agent must retry the save and, failing that, write as much of
   `RESULT.json`/an error file as it can before exiting, and the run must be
   marked `failed` with a human-and-agent-readable `error_message` — never a
   silent drop discovered later by a person querying the database.

### 4.2 A deploy run

Same shape, different payload and credentials:

- job tier: the specific revision's final rendered PNGs + ad metadata (name,
  campaign, destination URL)
- tenant tier: none needed beyond what's already baked into the ad
- credentials: Adstream login only (never the OpenAI key)
- tool: Kernel-driven browser, not an image model

The agent logs into Adstream, completes the create flow, uploads the creative,
publishes, **then navigates to the ad detail page and reads it back** — ad name
as normalized by Adstream, publish status — before it is allowed to report
success. A `deploys` row is only marked `verified=true` after that read-back, not
after the agent claims to be done. Kernel's recording API captures the whole
session; the recording path is saved to Storage and referenced from the
`deploys` row. **No recording, no deploy** — treat a run that produces no
recording as failed regardless of what the browser did.

---

## 5. Concurrency and isolation ("the horrifying test case")

Requirement: Emplifi opens a new task, Kahua opens a new task, Kahua edits
theirs, Emplifi edits the first, Emplifi opens a second — all firing at once, in
an order the system cannot predict — and **nothing crosses tenants**, nothing
requires a friendly order, and every output is traceable to its own inputs.

- Concurrency cap: a simple counter of `runs.status='running'`, enforced before
  claiming a new queued run (a Postgres row lock / `SELECT ... FOR UPDATE` on a
  single counter row is enough). No custom scheduler — a capped FIFO queue. The
  Nth+1 request waits in `queued` until a slot frees.
- Isolation is enforced **by construction**, not by policy: a sandbox's
  filesystem must never contain another tenant's brand kit or another job's
  request/comments, full stop, because hydration only ever writes the one
  `tenant_id`/`request_id` the run row names. There is no "don't peek" rule to
  enforce because the other tenant's files are simply never present in the box.
- Prove it, don't just assert it: run two different inspirations through
  concurrently and diff the outputs — if two outputs show influence from the
  same inspiration, something crossed. If you build any leak-detection check,
  first prove the check can actually fail: plant a real leak once on purpose and
  confirm the check catches it. A check that has never been shown to fail is not
  evidence of anything.

---

## 6. Resume and crash recovery

- **Resume for correctness**: getting back to revision 3 after revision 4 failed
  is just re-running the hydration recipe for revision 3 into a new sandbox. It
  should require no special-casing.
- **Resume under box death**: kill an in-progress sandbox on purpose (call the
  provider's kill/terminate API mid-run) at least once during development. Spin
  a new sandbox, rehydrate the same run, and confirm the agent proceeds with no
  awareness the previous box ever existed.
- **Partial-save recovery**: simulate a box killed at, say, minute nine of a
  ten-minute run, after the image-generation API call already succeeded (and was
  billed) but before the save completed. Document precisely, per state:
  - what a simple operator retry recovers automatically
  - what requires a human with database/storage access
  - whether/how you avoid re-billing an image-generation call on retry (a nice
    to have — e.g. checking Storage for an already-produced plate for that exact
    prompt/revision before regenerating — but not mandatory)
- Save every run's full raw agent transcript to that tenant's own
  `jobs-{tenant_id}` bucket at `{request_id}/revisions/{n}/agent-transcript.jsonl`
  regardless of whether the run succeeds. You will need these to debug the above; the grader wants
  them too.

---

## 7. Build order

Do not start any sandbox work until Phase 0 is done. Every later phase becomes
undebuggable if you can't yet tell a skill problem from a hydration problem from
a database problem.

### Phase 0 — Local skill gate (no sandbox, no backend)

Run the ad-generation skill directly in a local Claude Code/Codex session against
both `design-brains/design-brains/{emplifi,kahua}` brains. Goal: on demand,
produce on-brand ads you would show a customer, for both brands, at all four
canvas sizes (1080×1080, 1200×628, 1080×1350, 728×90), reliably and in bulk
(~20 ads). If any target size can't be produced by your sizing/plate-generation
approach, that is itself a finding to write down, not something to paper over.
Do not proceed to Phase 1 until this is boring.

### Phase 1 — Generate an ad from a brain (in a sandbox)

Wire Phase 0's working skill into the real pipeline: request intake → resolve
brand (tenant tier, fetched fresh) → generate one full-canvas plate per size via
`gpt-image-2` → HTML overlay for every word and the logo at true proportions →
render to PNG → agent looks at the PNG and self-critiques → agent saves
everything to Storage → DB rows updated. Must work for both brands. A pipeline
that only works for one brand is not a pipeline.

### Phase 2 — The engine (graded hardest)

Harden hydration, storage, concurrency, and resume per §§3–6. Done when:

- the horrifying concurrency case runs with evidence nothing crossed
- a killed box comes back via a fresh box with the agent unaware anything
  happened
- a mid-run crash has been deliberately caused at least once, and you can state
  exactly which resulting states a retry recovers and which don't
- a brand-new third brand (same file shape as Kahua/Emplifi) can be dropped in
  and taken through a new task + an edit, live, with **zero code changes** —
  because nothing in the codebase may reference "kahua" or "emplifi" by name

### Phase 3 — Feedback surface (pinned comments)

Frontend: click-or-drag a region on a rendered canvas to leave a comment; show
revision history; let older-revision comments collapse/hide. Backend: a comment
hydrates into an edit run as job-tier data — right tenant, right task, right
revision, right region coordinates, and a prompt describing what the human
meant. Do not build a classifier deciding "text edit vs full regen" — that's the
agent's call. Done when a comment left in the frontend round-trips end to end
with nothing manual in between: it reaches the agent attached to the correct
revision, the agent acts on it, and the updated asset reappears in the frontend.

Note for `DECISIONS.md`, don't build: what happens to a pin when the asset
regenerates and the pinned region no longer matches anything (stale / resolved /
orphaned).

### Phase 4 — Deploy

Per §4.2: browser-driving agent inside the `deployment` sandbox, credentials
scoped to Adstream only, Kernel recording on every run, mandatory detail-page
read-back before declaring success. Should be small if Phases 1–2 were built
correctly — if deployment needs a second subsystem instead of reusing the same
hydrate → run → save → destroy shape, something upstream was under-designed.

Adstream quirks to account for (`https://adstream.bhairav.workers.dev/`,
`demo@adstream.test` / `adstream`):
- ad names are normalized on save — verify against the *stored* name, not what
  you typed
- Next/Publish stay disabled until a page's fields are complete — the agent
  needs to actually wait for/detect this, not assume timing
- publish takes 2–9 seconds
- duplicate names are allowed — don't rely on name uniqueness for verification
- the success toast lasts 6s and persists across navigation — don't treat toast
  presence as proof; the detail page is the only source of truth

---

## 8. Known brand-data inconsistencies (already found — do not build reconciliation logic)

The brand data is deliberately inconsistent. Per the brief: notice it, pick one
value, apply it everywhere, write down the choice. Do not build adjudication
machinery.

- **Emplifi `DESIGN.md` vs `brand/tokens.json` disagree**: secondary color
  (`#6765FE` vs `#5B5BD6`), corner radius (`12px` vs `16px`), h1 size (`48px` vs
  `56px`). Rule to apply: `DESIGN.md` always wins — this matches `SKILL.md`'s own
  stated resolution order (`tokens.json` is "a convenience for tooling... not
  permitted to contribute a value that DESIGN.md also states").
- **Emplifi `asset_manifest.json`** contains a `logo_lockup` entry stamped with
  `brand_kit_id: "bk-kahua-2026"` inside Emplifi's own manifest. Rule to apply:
  filter every asset lookup by the request's pinned `brand_kit_id`; an asset row
  whose kit id doesn't match the active tenant is invisible, never a fallback.
- **Kahua `asset_manifest.json`** references `brand/kahua-logo-white.svg` for
  `logo_reverse`, but that file does not exist in `kahua/brand/`. Rule to apply:
  treat a manifest entry whose file doesn't resolve as unavailable — omit that
  asset or escalate in `RESULT.json`; never substitute another tenant's logo or
  typeset a text placeholder for it.

Apply the same posture to whatever inconsistency the day-two third brand turns
out to have — the rule is "pick one, document it," not "handle these three
specific cases."

---

## 9. Explicitly out of scope

Do not spend time on any of these; they are named in the brief as time sinks
that hurt finishing, not requirements:

- Brand-kit versioning or a rollback UI (assume the kit in effect is simply
  whatever's current in Storage when a run starts)
- Any automated "does this look on-brand" scoring system
- A classifier for edit routing (text patch vs full regen)
- A custom scheduler beyond a capped FIFO queue
- A permission/sandboxing system limiting what the agent's own credentials can
  reach (note the blast radius in `DECISIONS.md` instead)
- Any performance/cold-start optimization

---

## 10. Acceptance checklist

- [ ] Phase 0: 20 on-brand ads, both brands, all 4 sizes, generated locally with
      no sandbox involved
- [ ] Phase 1: same, but through the real pipeline (sandbox → Storage → DB →
      frontend), both brands
- [ ] Phase 2: concurrent cross-tenant run with proof of no leakage; box killed
      and resumed with the agent unaware; a deliberate mid-run crash with
      documented recoverable/unrecoverable states; a new third brand onboarded
      live with zero code changes
- [ ] Phase 3: a comment placed in the frontend round-trips to a correct edit
      and back with no manual steps
- [ ] Phase 4: a deploy fired from the frontend ends in a verified Adstream
      detail-page read-back plus a saved recording

## 11. Deliverables

- Full repo, with git history intact
- Complete, unedited raw transcripts of every agent session — dead ends
  included, not cleaned up
- Everything the system produced: generated ads (both brands + the third),
  plates, a dump of the Storage buckets, a database dump, all deploy recordings
- `DECISIONS.md`, covering at minimum:
  - what was built vs stubbed, and what you'd do next
  - the storage/hydration/resume model and why
  - what happens when the brand changes between revision 3 and revision 6
  - what happens to a pinned comment when its region no longer matches anything
    after regeneration (stale / resolved / orphaned)
  - the concurrency cap chosen and what happens to the request that exceeds it
  - the blast radius of the agent's credentials in each sandbox type
  - which of your own claims you're least sure of

---

## 12. Reference links

- OpenAI Images: https://platform.openai.com/docs/guides/images
- OpenAI computer use: https://platform.openai.com/docs/guides/tools-computer-use
- Claude Agent SDK: https://docs.claude.com/en/api/agent-sdk/overview
- Claude Code headless (`claude -p`): https://docs.claude.com/en/docs/claude-code/headless
- E2B: https://e2b.dev/docs
- Kernel: https://docs.onkernel.com
- Playwright: https://playwright.dev/docs/intro
- Adstream (stand-in ad platform): `https://adstream.bhairav.workers.dev/` —
  `demo@adstream.test` / `adstream`
