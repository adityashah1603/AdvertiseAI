# BUILD_GUIDE.md — Step-by-Step Execution Plan for the Coding Agent

This is the literal task list. `ROADMAP.md` is the architecture and why;
`DECISIONS.md` is the policy answers; this file is the ordered sequence of
steps to actually execute, each with its own constraints and its own
definition of done.

## How to use this document

1. Read in this order before writing anything: `SKILL.md` →
   `design-brains/emplifi/DESIGN.md` →
   `design-brains/kahua/DESIGN.md` → `ROADMAP.md` →
   `DECISIONS.md` → this file.
2. Execute steps **in order**. Every step after Step 1 assumes the previous
   step's "Definition of done" is actually true, not assumed true. If a
   definition of done fails, stop and fix it before moving forward — do not
   build the next layer on top of an unverified one.
3. The "Constraints" list in §0 applies to **every single step below**, not
   just the step where a matching topic first comes up. Re-check it before
   marking any step complete.
4. If a step conflicts with §0, §0 wins. Say so out loud (in the transcript,
   in `DECISIONS.md`) rather than quietly working around it.

---

## §0. Constraints that apply to everything you build (the strict "don't"s)

These come from the trial brief directly. Any violation fails the whole
project regardless of how good anything else is — treat them as harder rules
than anything phrased as a "requirement" below.

- **Don't** let anything except the agent itself move files out of a sandbox.
  No backend job that reads a sandbox's filesystem after a run, polls its
  disk, or rsyncs an "out" directory. The agent uploads its own output, from
  inside the box, before it exits.
- **Don't** give a sandbox tenant- or task-specific identity. No naming, no
  template, no image, no environment variable that says "this box is Kahua's"
  or "this box is for request X" ahead of time. A sandbox is anonymous until
  it's told, at hydration time, whose data to load.
- **Don't** run the agent as a subprocess of your backend/API process. It must
  run inside an actual isolated sandbox (E2B), reached only via that
  provider's API. A queue in front of it is fine; co-location is not.
- **Don't** run any agent — especially the deployment one — on a developer
  laptop.
- **Don't** let any state exist only on a box. If a box is killed, recovery
  must come from Postgres + Storage, never from "what was still on the box."
- **Don't** require requests to arrive in any particular order, and don't test
  only with a convenient order.
- **Don't** build a brand-conformance scoring system. A human/agent looking at
  the rendered PNG is the only allowed judge of "does this look on-brand."
- **Don't** build a classifier that decides "text edit vs. full regeneration"
  for an incoming comment — that's the generation agent's own judgment call.
- **Don't** build brand-kit versioning/rollback, a custom scheduler beyond a
  capped FIFO queue, or a credential permission system. Answer these in
  `DECISIONS.md` instead (already drafted there).
- **Don't** optimize for cold-start latency or any other performance metric.
  Finishing beats polishing.
- **Don't** treat `starter/requests/*.example.json` as a schema to conform to,
  or as a fixture defining request ordering to design around.
- **Don't** silently reconcile the known brand-data inconsistencies
  (`DECISIONS.md` §3 notes them). Pick the stated resolution rule and apply it
  everywhere; don't build adjudication logic.

---

## §1. Suggested repo layout

```
/app                    # Next.js frontend
/worker                 # Python: orchestrator, hydration, agent invocation
  /orchestrator          # run claiming, concurrency cap, sandbox lifecycle
  /hydration             # hydrate_generation(), hydrate_deploy() — pure functions
  /sandbox_images
    /generation           # Dockerfile/E2B template: Claude Agent SDK, OpenAI SDK, fonts, renderer
    /deployment           # Dockerfile/E2B template: Claude Agent SDK, Playwright, Kernel SDK
/skill                  # global tier: copy of SKILL.md + prompt templates, versioned here
/supabase
  /migrations            # SQL for tables in ROADMAP.md §3.1
  /seed                  # scripts to load design-brains/* into brand-kits/{tenant_id}/ storage
ROADMAP.md
DECISIONS.md
BUILD_GUIDE.md
.env.example            # documents every required var, no real values
```

`design-brains/`, `inspirations/`, `starter/` (already in the repo) stay
exactly as provided — they are input data and a seed source, never a
scaffold to build on top of or edit in place.

---

## Step 0 — Environment and accounts

**Do:**
- Create `.env.example` documenting every variable needed:
  `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `E2B_API_KEY`, `KERNEL_API_KEY`,
  `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `ADSTREAM_EMAIL`,
  `ADSTREAM_PASSWORD`, `GENERATION_CONCURRENCY_CAP`,
  `DEPLOYMENT_CONCURRENCY_CAP`.
- Confirm real values are available (see the CEO-call questions already
  raised) before spending anything.

**Constraints:** no real secret ever committed; `.env` stays git-ignored.

**Definition of done:** every var in `.env.example` has a real counterpart in
a local, uncommitted `.env`, and a trivial script can print "connected" for
Supabase, E2B, and one Anthropic call.

---

## Step 1 — Phase 0: local skill validation (no infrastructure)

**Do:**
- In a local Claude Code/Codex session (no backend, no sandbox, no database),
  point the model at `SKILL.md` and one brain at a time.
- Generate ads for Emplifi across all four sizes (1080×1080, 1200×628,
  1080×1350, 728×90). Look at every PNG yourself.
- Repeat for Kahua.
- Iterate on the skill instructions until you get ~20 ads per brand you would
  actually show a customer, reliably, not as a lucky run.

**Constraints:** nothing here touches E2B, Supabase, or the frontend. If
you're tempted to start infrastructure before this is boring, don't — you
won't be able to tell a skill bug from a plumbing bug later.

**Definition of done:** 20+ defensible ads per brand, all four sizes, and you
can say in one sentence what would make you reject one you generated.

---

## Step 2 — Data layer

**Do:**
- Create the tables from `ROADMAP.md` §3.1 (`tenants`, `requests`,
  `revisions`, `assets`, `comments`, `runs`, `deploys`) as Supabase
  migrations.
- Create the storage layout from `ROADMAP.md` §3.2.
- Write a seed script that reads `design-brains/{emplifi,kahua}`
  from this repo and uploads each into `brand-kits/{tenant_id}/` in Storage,
  inserting the corresponding `tenants` rows.

**Constraints:** no table or column may be tenant-specific (no
`kahua_requests` table, no `is_kahua` flag). Everything distinguishes tenants
only via `tenant_id` foreign keys.

**Definition of done:** both tenants' brand kits are fetchable from Storage
by `tenant_id` alone, with no code path that knows either name.

---

## Step 3 — Generation sandbox + hydration + orchestrator

**Do:**
- Build the `generation` sandbox image: Python, Claude Agent SDK, OpenAI SDK,
  the fonts-and-render toolchain, no Adstream credentials, no browser.
- Write `hydrate_generation(tenant_id, request_id, revision_number)`: a pure
  function that, given only those ids, produces the exact set of files a
  fresh sandbox needs (global skill files, that tenant's brand kit pulled
  fresh, that job's request/copy/prior-revision/open-comments data).
- Write the orchestrator: claim a queued `runs` row → open a fresh E2B
  sandbox with a random id → call `hydrate_generation` and write its output
  into the sandbox → launch the agent inside the sandbox with the generation
  prompt → wait for the run to report done → verify the expected files landed
  in Storage → mark the DB row `succeeded`/`failed` → destroy the sandbox.
- Inside the sandbox, the agent's own job (per `SKILL.md`): generate the
  plate via `gpt-image-2`, author the HTML overlay for every word and the
  logo, render the canvas to PNG, **look at the PNG and self-critique**
  before finishing, then save everything itself to
  `jobs/{request_id}/revisions/{n}/` and write `RESULT.json`.

**Constraints:** the orchestrator never reads the sandbox's filesystem to
retrieve results — it only checks that Storage received what it expects. If
a save fails, the agent must retry and, failing that, write a clear error
into `RESULT.json` and exit non-zero — the run must fail loudly, not go
quiet.

**Definition of done:** triggering one run end-to-end (script or API call is
fine, frontend not required yet) produces real assets in Storage and updated
rows in Postgres, for both tenants independently.

---

## Step 4 — Minimal frontend

**Do:**
- A request-submission form: tenant, campaign, copy fields, canvas sizes,
  inspiration filenames (checkbox list from that tenant's `inspirations/`).
- A revision viewer: render the stored PNGs per canvas size for a given
  request/revision.

**Constraints:** the frontend talks only to your backend API — it never
touches Supabase Storage/E2B/Anthropic/OpenAI credentials directly.

**Definition of done:** you can submit a request through the UI and see the
resulting ad without touching a script or the database directly.

---

## Step 5 — The engine: concurrency, resume, crash recovery

This is graded hardest — don't rush it to get to the feedback UI.

**Do:**
- Implement the concurrency cap (separate counters for generation vs.
  deployment runs) and the FIFO queue behavior from `DECISIONS.md` §3.3.
- Run the "horrifying test case": Emplifi opens a task, Kahua opens a task,
  Kahua edits it, Emplifi edits the first, Emplifi opens a second — fired
  concurrently, order not controlled by you. Use two different inspirations
  across the concurrent runs and diff the outputs for cross-contamination.
- Kill an in-progress sandbox on purpose via the E2B API mid-run. Spin a new
  sandbox, rehydrate the same run from Storage/Postgres, and confirm the
  agent continues with no special-casing.
- Crash a run deliberately partway through (after the image-generation call
  succeeds but before the save completes). Document, in `DECISIONS.md`,
  exactly which resulting states an operator retry recovers automatically and
  which need manual database/storage intervention.
- If you build any automated leak-detection check, first prove it can fail:
  plant one real cross-tenant leak on purpose and confirm the check catches
  it before trusting it on real runs.
- Build a throwaway fourth "brand" folder yourself (same shape as
  Kahua/Emplifi) and push a new task + an edit through the system with zero
  code changes, as a dry run before the real day-two brand shows up.

**Constraints:** no manual "friendly ordering" in your test — the whole point
is proving arbitrary interleavings don't cross. A green check alone is not
evidence; keep the logs/screenshots that show the hydration path was actually
exercised correctly.

**Definition of done:** every bullet in `ROADMAP.md` §7 Phase 2 is checked
with saved evidence, and you can explain, from the hydration code (not from
"it passed"), why leakage is structurally impossible.

---

## Step 6 — Feedback surface (pinned comments)

**Do:**
- Frontend: click-or-drag a region on a rendered canvas to leave a comment;
  a revision-history view; "hide older revision comments."
- Backend: a submitted comment writes a `comments` row scoped to
  `(tenant_id, request_id, revision_id, canvas_name, region)` and creates a
  new queued `runs` row of type `edit` whose hydration includes that
  comment's region and body as job-tier data, plus the current assets.
- Apply the open/resolved/orphaned rules from `DECISIONS.md` §3.2 exactly:
  resolved when an edit run that named the comment completes; orphaned when a
  comment's revision is no longer latest and nothing closed it; never
  auto-remap coordinates or auto-diff pixels.

**Constraints:** don't build logic that decides text-edit-vs-regenerate — let
the agent decide from the prompt. Don't build pixel-diffing for staleness
detection.

**Definition of done:** a comment placed in the frontend reaches the correct
tenant/task/revision, the agent acts on it, and the updated asset appears
back in the frontend with no manual step in between.

---

## Step 7 — Deployment sandbox

**Do:**
- Build the `deployment` sandbox image: Python, Claude Agent SDK, Playwright,
  Kernel SDK. No OpenAI key, no brand-kit access beyond the one revision's
  final rendered assets.
- Write `hydrate_deploy(tenant_id, request_id, revision_number)`.
- Agent script inside the sandbox: log into Adstream → complete the create
  flow → upload the creative → publish → **navigate to the ad detail page and
  read it back** (normalized name, published status) before reporting
  success.
- Wire Kernel's recording API so every deploy run produces a recording saved
  to `deploys/{request_id}/revisions/{n}/recording.mp4`, referenced from the
  `deploys` row.
- Wire a "Deploy" action in the frontend that triggers this run and displays
  the verified result + a link to the recording.

**Constraints:** the browser must run where the agent runs (inside the
sandbox), never on your machine. A run that produces no recording is a failed
run regardless of what the browser did on screen. Account for Adstream's
quirks: name normalization on save, Next/Publish disabled until fields are
complete, 2–9s publish latency, duplicate names allowed, and a success toast
that persists across navigation and proves nothing on its own.

**Definition of done:** a deploy fired from the frontend ends with a verified
detail-page read-back and a recording you can watch.

---

## Step 8 — Packaging and write-up

**Do:**
- Export: full Postgres dump, full Storage bucket contents, every agent
  transcript (raw, unedited, dead ends included).
- Finish `DECISIONS.md` §1, §2, §5 (what was built/stubbed, what's next,
  which claims you're least sure of) — these were left as placeholders on
  purpose until real build experience could answer them honestly.
- Write a top-level `README.md`: how to run the frontend, the worker, and the
  seed script from a clean checkout.

**Definition of done:** everything in `ROADMAP.md` §11 is present in the
repo, and a clean checkout plus the documented env vars is enough for someone
else to run the whole system.

---

## Quick-reference: definition-of-done gate before advancing a step

Before marking any step complete, re-read §0 and answer, in your own words:

- Did anything but the agent move files out of a box?
- Does any sandbox, table, or file path encode a tenant or task ahead of
  hydration time?
- Did the agent run anywhere but inside an isolated sandbox?
- If I killed the box right now, would I lose anything that mattered?
- Did I just test a convenient ordering, or an arbitrary one?

If any answer is uncomfortable, that step isn't actually done yet.
