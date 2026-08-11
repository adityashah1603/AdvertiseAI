# DECISIONS.md

This is the write-up that goes with the code, not a design doc that precedes it.
The four policy questions in §3 don't have clean answers, so they're answered
here as reasoned positions rather than built as features — per `ROADMAP.md` §9,
none of these get a version graph, a diffing engine, or a permission system.
§1, §2, §6, and §7 consolidate what used to be four separate running-notes
files (`worker/sandbox_images/generation/phase0/{README,FLOW_PHASE_0}.md`,
`phase1.md`, `Phase3.md`) — folded in here and deleted once this file could
stand on its own as the one authoritative account of what was built, found,
and fixed. Nothing substantive from those files was dropped, only compressed.

---

## 1. What was built vs. stubbed

| Area | Status | Notes |
|---|---|---|
| Phase 0 — local skill gate | ✅ done | 20+ real ads across Emplifi, Kahua, and a self-built Duolingo generalization test, generated locally (no sandbox) via `gpt-image-2` + hand-authored HTML overlays. Full findings in §6. |
| Phase 1 — generation pipeline | ✅ done | Same pipeline live-tested for 4 brands total (Emplifi, Kahua, Duolingo, and Patagonia — onboarded blind, day-two style, with zero code changes) through the real sandboxed path: hydrate → E2B sandbox → Claude Agent SDK → Storage → Postgres. |
| Phase 2 — the engine (hydration/concurrency/resume) | ✅ done | Concurrency cap proven under real load (interval-overlap analysis, not just "it didn't crash"), a real mid-run `Sandbox.kill()` resumed cleanly, a real crash mid-save had its recoverable/unrecoverable states documented (§6), leak-detection proven able to catch a planted leak before being trusted. |
| Phase 3 — feedback surface (pinned comments) | ✅ done | Backend hydration of comments into an edit run, a real frontend with click-or-drag area pinning, and the `resolved` status transition (§6) all work end to end. Comment `stale`/`orphaned` transitions are deliberately unbuilt — the brief itself says not to (§3.2). |
| Phase 4 — deployment | ☐ not started | No `deployment` sandbox image, no `hydrate_deploy()`, no Adstream automation, no `deploys` table. The next thing to build — see §2. |

Stubbed by choice, not oversight: brand-kit versioning/rollback, a
brand-conformance grader, an edit-routing classifier, a scheduler beyond the
capped FIFO queue, and a credential permission system — all explicitly named
in the brief as time sinks, not requirements.

Known, honest gap in Phase 1/2's own completeness: inspiration image files
*are* fetched into the sandbox now (a real backend + UI feature, not just
filenames passing through — see §6), but the concurrent-*edits*-across-tenants
half of "the horrifying test case" was only proven with 2 tenants (Emplifi,
Duolingo) in the cleanest run, not all 4 at once — the other two had already
consumed their "latest revision" slot in an earlier, sandbox-SDK-broken
attempt (§6) and weren't re-generated fresh just to pad the number.

---

## 2. What I'd do next

1. **Build Part 4 (Deploy).** Per the brief, this should be small if Phases
   1–2 were built correctly: same hydrate → sandbox → save → destroy shape,
   plus a browser (Kernel or Playwright-in-the-box), the Adstream credential,
   and a mandatory detail-page read-back before a `deploys` row is allowed to
   say `verified=true`.
2. **Run exactly one long-lived dispatcher process per environment**, or make
   every caller of `claim_next_run()` agree on the same cap. §6 documents why:
   the cap is enforced per-caller, not as one system-wide number, so two
   dispatcher processes with different configured caps can jointly push peak
   concurrency to the higher of the two. Not a bug — a real operational fact
   worth designing deployment around.
3. **Pin every venv's dependencies, always** — `worker/orchestrator/` had no
   `requirements.txt` at all until this was caught live (§6); that's now
   fixed, but it's worth an audit pass across the repo for any other
   unpinned install.
4. **Re-billing on retry is not avoided.** A crash after a billed
   `gpt-image-2` call but before save currently re-bills on retry (confirmed
   live, §6). The brief calls this a nice-to-have, not mandatory — the fix
   would be checking Storage for an already-produced plate at that exact
   prompt/revision before regenerating.
5. **Automatic staleness detection now exists for `running` rows** (§6) but
   is deliberately simple (a fixed 20-minute timeout inside
   `claim_next_run()`). A production version might want this configurable
   per sandbox timeout rather than hardcoded.
6. **RLS policies remain unbuilt.** Currently harmless — nothing but
   server-only, service-role-key code ever touches Supabase (the frontend's
   client components only call the internal API, never Supabase directly) —
   but this stops being true the moment any client-side Supabase access path
   is added, and should be revisited before that happens, not after.
7. **The concurrent-edit test's 4-tenant proof is incomplete** (§1) — worth
   re-running with all 4 tenants freshly eligible for a fuller version of
   "the horrifying test case"'s edit half.

---

## 3. The four questions this brief routes here

### 3.1 What happens when the brand changes between revision 3 and revision 6?

**Position:** never freeze a brand kit to a task. Every run — including a run
that produces revision 6 of a task whose revision 3 is months old — pulls the
tenant's brand kit fresh from `brand-kit-{tenant_id}/`, per `ROADMAP.md` §4.1.
The alternative (pin the kit a task was "born with") guarantees visual
consistency across a task's own revisions, but it also guarantees that an
operator can publish a stale, off-brand ad without ever being told the brand
moved on — worse than an unexpected visual jump.

The one thing worth building, because it's cheap and closes the actual risk:
when a new revision resolves a brand kit, hash/fingerprint the kit it just
pulled (e.g. hash of `DESIGN.md` + `tokens.json` + manifest contents) and
compare it to the fingerprint the task's most recent prior revision used. If
they differ, don't silently re-render in the new palette — record the diff in
that revision's `RESULT.json` (old fingerprint, new fingerprint, which fields
changed) and surface it in the frontend as a visible note on the revision
("this revision picked up an updated brand kit"). No version graph, no
rollback — just don't let a brand change happen invisibly. **Not yet built**
— `hydrate_generation()` already re-fetches the brand kit fresh every call
(the structural prerequisite), but the fingerprint-diff-and-surface step
itself is still on the "what I'd do next" list.

**Least sure of:** whether "surface it and move on" is enough for a real
operator workflow, or whether a brand change mid-task should actually block
generation until a human acknowledges it. Went with non-blocking because the
brief says not to build approval/versioning machinery here.

### 3.2 What happens to a pinned comment when the asset regenerates and the thing under it moved?

**Position:** a comment is immutably scoped to the revision it was left on —
`comments.revision_id` never changes. Three states, no image diffing, no
coordinate remapping:

- **`open`** — left on the current latest revision, not yet acted on.
- **`resolved`** — an edit run that named this comment in its prompt completed
  and produced the next revision. Resolved regardless of whether the new
  render's pixels at that region actually look different — "the agent addressed
  it" is the resolution condition, not "the pixels changed," because verifying
  the latter is exactly the image-diffing subsystem the brief says not to
  build. **Built and verified**: `execute_run.py` resolves every `open`
  comment on a revision the instant a real edit run against its successor
  succeeds, derived purely from which run succeeded against which prior
  revision (no agent-side reporting needed, since hydration always pulls
  *every* open comment into the prompt, never a filtered subset).
- **`orphaned`** — the comment's revision is no longer the latest, and no edit
  run ever closed it. This happens naturally when a second, unrelated edit
  request lands before someone acts on an earlier comment. An orphaned comment
  is never auto-carried into a future prompt and never auto-remapped to new
  coordinates on a new render — a human has to explicitly re-raise it against
  the current revision if it's still relevant. **Deliberately not built** —
  this is exactly the adjudication machinery the brief says to answer in
  writing, not build.

Older-revision comments (any status) collapse under "hide older revision
comments" in the UI but are never deleted — full history stays inspectable.
The "N open" counter only counts `open` comments on the latest revision, and
now actually decreases as edits resolve them.

**Least sure of:** whether silently orphaning (rather than, say, prompting the
operator "this comment's revision is out of date, re-raise it?") loses real
feedback in practice. Chose silent-but-visible over an interrupt because the
brief explicitly wants this answered in writing, not built as a workflow.

### 3.3 What's the concurrency cap, and what happens to the request that exceeds it?

**Position:** two independent caps, not one — generation sandboxes and
deployment sandboxes contend for different resources (image-model rate limits
vs. browser sessions) and should never block each other. Both live as a
runtime environment variable (`GENERATION_CONCURRENCY_CAP`), not a literal in
code — the actual number should be set from the sandbox provider's real
concurrency limits and cost tolerance, which is an operational fact, not a
design one.

Enforcement: `claim_next_run(p_cap)`, a Postgres function that locks a
sentinel row (`dispatch_lock`) `FOR UPDATE`, counts `runs.status='running'`
fresh from truth, and claims the oldest `queued` run via `SKIP LOCKED` only if
there's room. A request beyond the cap sits in `runs.status='queued'` —
visibly, in the UI, not silently dropped or retried blindly — and is picked
up FIFO as running slots free. No priority tiers, no per-tenant fairness
guarantees: the brief explicitly calls a scheduler a solved problem nobody
asked for.

**Real nuance found, not assumed:** the cap is enforced *per caller*, not as
one system-wide ceiling — `claim_next_run()` checks whichever `p_cap` value
the calling process passes it. Running two dispatcher processes concurrently
with different configured caps (observed for real: a live `--serve` process
at the `.env` default of 3, and a test script's own dispatcher instance at 2)
let the true peak reach 3, even though neither caller individually exceeded
its own stated cap. Confirmed by re-running with only one process live: peak
dropped to exactly the single cap. See §2 item 2.

**Least sure of:** FIFO with no per-tenant fairness means one tenant submitting
a burst of requests can make another tenant's single request wait behind all of
them. Accepted as fine for this trial's scale; would revisit for production.

### 3.4 What's the blast radius of the agent's credentials?

**Position:** credentials are scoped per sandbox type, not shared, and are
short-lived tokens minted per run — never the same standing key handed to
every box.

**Generation sandbox** gets: an OpenAI Images API key, an Anthropic API key,
and one narrow, single-path, single-operation, time-limited signed Storage
upload URL *per expected output file* (`upload_urls.py`, minted before the
sandbox exists, using the trusted service-role key the sandbox itself never
sees). It reads that tenant's own brand-kit and inspirations buckets fresh
via the orchestrator's own trusted fetch (not a credential handed to the
sandbox at all — the sandbox receives files, not bucket access). It never
receives the Adstream credential, never receives another tenant's data, and
never receives raw database credentials — all state transitions go through
backend endpoints that validate tenant/revision ownership server-side.

*Worst case if a generation run is fully compromised:* it can burn OpenAI/
Anthropic budget and corrupt or overwrite files within its own job's revision
folder (each signed URL is scoped to one exact path). It cannot read or touch
another tenant's data (it was never given the credential to), cannot publish
anything (no Adstream credential), and cannot corrupt the database directly
(no DB credential at all).

**Deployment sandbox** (not yet built) will get: the Adstream login (a single
shared demo account in this trial; in production this would be one credential
per tenant's ad account, scoped identically) and the Kernel session/recording
API key, plus read access to only the one revision's final rendered assets
it's deploying. It will never receive the OpenAI key and never receive any
tenant's brand-kit or font files.

**Least sure of:** in this trial Adstream only has one demo login to give
every tenant, so the "one credential per tenant" scoping described above is
aspirational, not actually enforceable end to end once Part 4 is built —
worth flagging plainly rather than implying it will be live by construction.

---

## 4. Feedback surface: why pinned comments over chat

Pinned comments were chosen over a chat box specifically because the brief
grades *hydration correctness* (right tenant, right task, right revision, right
coordinates) harder than it grades conversational quality. A region-anchored
comment forces the system to carry precise structured data (`canvas_name`,
`x,y,width,height`, `revision_id`) through the entire pipeline, which is a
stronger test of the storage model than free-text chat would be. The cost was
real: more frontend work (a real click-or-drag pin UI, now built), and the
stale/resolved/orphaned question in §3.2 that a chat thread wouldn't raise at
all. Traded that cost for the sharper demonstration of the thing actually
being graded.

---

## 5. Claims I'm least sure of

- Whether a fingerprint-diff-and-surface mechanism (§3.1) is really enough for
  a real operator workflow, or whether some brand changes should block
  generation outright until acknowledged.
- Whether silently orphaning a stale comment (§3.2) loses real feedback in
  practice versus an explicit "this is stale, re-raise it?" prompt.
- Whether FIFO with zero per-tenant fairness (§3.3) holds up once request
  volume is real rather than trial-scale.
- Whether "one shared Adstream login standing in for per-tenant credentials"
  (§3.4) is a safe enough approximation to build Part 4 against, or whether
  it should be flagged as blocking for a real multi-tenant deploy.
- Whether the day-two brand test is fully honest: Duolingo (self-built) and
  Patagonia (onboarded blind mid-build) both went through with zero code
  changes, which is real evidence — but neither is a brand actually handed to
  me cold by someone else, which is what the brief's own walkthrough test is.
- Whether 2-tenant concurrent-edit evidence (§1, §6) is convincing enough on
  its own, or whether the 4-tenant version needs to be re-run before this
  claim is fully closed.
- Whether the render-quality bar itself (SKILL.md's "look at it" step) was
  applied as rigorously on every one of the ~30+ real renders produced across
  this build as it was on the ones that got a documented second pass (the
  type-scale audit in §6 found real violations that survived one full review
  pass each) — a full second pass across everything was never done, only
  spot-audits.

**Transparency note, carried forward rather than buried:** during Phase 0,
`.gitignore` was observed being edited to re-hide `ROADMAP.md`/`DECISIONS.md`
immediately after they'd been deliberately un-hidden, accompanied by a
tool-result instruction not to mention it. It was flagged to the user at the
time instead of complied with, and hasn't recurred since. No live instance of
this exists in the current session's own tool results, but it's a real,
on-the-record anomaly worth staying aware of.

---

## 6. Key findings from the build

Condensed from the full working notes (previously three separate files, now
folded in here). Not every minor fix is listed — only the ones with lasting
design consequences.

**Image generation (`gpt-image-2`, Phase 0/1):**
- Real API bounds, confirmed against official docs: edges must be multiples
  of 16px, max edge 3840px, long:short ratio ≤ 3:1, total pixels between
  655,360 and 8,294,400. None of the brief's four target sizes are natively
  divisible by 16; fixed via nearest-valid-size generation + one uniform
  resize (never a crop/stretch — SKILL.md's "same aspect ratio" rule holds).
- **728×90 is architecturally impossible** through this API (8.09:1 ratio,
  and even a divisible-by-16 candidate falls under the pixel floor). Dropped
  from scope with the finding documented, per the brief's own "if your sizing
  logic can't produce one of them, that's a finding" escape hatch. A 9:16
  "story" canvas (Instagram/TikTok/Reels' actual native shape, well within
  the real bounds) was substituted.
- Type-scale role-mapping mistakes recurred across multiple brands and
  canvases (using a table value in the wrong role, or scaling type to fit a
  canvas instead of repositioning/cutting copy) — fixed with an explicit,
  named-past-mistake instruction in `agent_runner.py`'s system prompt, not by
  adding a validator.

**Sandbox mechanics (E2B):**
- Default 1GB sandboxes OOM'd installing dependencies at runtime → a custom
  pre-built template (`cq-generation-v1`) with deps + Chromium baked in.
  Explicitly checked against disqualifier #2: identical template for every
  brand, zero tenant/task identity baked in, only software — matches the
  brief's own hydration model ("imagine SSHing into the box, typing `claude`
  ... and walking away").
- `Sandbox.create` API broke **twice**, in opposite directions: `e2b==1.0.5`
  had no `.create()` classmethod (constructed via `Sandbox(...)` directly);
  after an unpinned upgrade to `e2b==2.38.0` mid-build, direct `Sandbox(...)`
  became reconnect-only and `.create()` became required again. Root cause the
  second time: `worker/orchestrator/` had no `requirements.txt` at all. Fixed
  by centralizing all sandbox creation in `sandbox_factory.py` (the one place
  that matches whatever's actually pinned) and adding the missing pin.
- The multi-process concurrency-cap nuance (§3.3) — caught live while
  re-running the concurrent-edit test with a second dispatcher unexpectedly
  live.

**Concurrency, resume, crash recovery (Phase 2, `ROADMAP.md` §5–§6):**
- Real concurrent batch (cap=2, 4 requests across 3 tenants): peak overlap
  measured via interval analysis, exactly 2; every output independently
  verified to contain only its own headline. Leak-detection logic itself
  proven able to catch a real, deliberately planted mislabeled leak before
  being trusted on real runs (per the brief's explicit instruction).
- Real concurrent edit batch (cap=2, 2 tenants once the sandbox-SDK bug above
  was fixed): peak overlap exactly 2; each edit's unique marker string
  appeared only in its own output.
- Real mid-run `Sandbox.kill()`: `plate.png`/`overlay.html` (checkpointed
  before the kill) survived; `render.png`/`RESULT.json` did not. The run was
  automatically marked `failed` with a clear error — no stuck row. A plain
  re-enqueue of the same revision completed cleanly with the agent unaware
  anything had happened. Re-billing on retry is **not** avoided (a real,
  differently-sized image-gen call was made again) — matches the brief's
  "nice to have, not mandatory."
- A `running` row whose sandbox died outside `execute_run.py`'s own exception
  handling (a manual kill, a crash) does **not** self-heal on its own —
  observed for real once, corrected by hand at the time, now fixed
  structurally: `claim_next_run()` expires any row `running` past 20 minutes
  (a margin above the sandbox's own 15-minute timeout) on every call.
- `execute_run.py` originally never touched the `revisions` table at all —
  successful runs left `revisions.status` stuck `pending` forever. Found via
  a real orphaned-revision audit against live Storage contents, fixed, and
  verified live.
- Comment `resolved` status (§3.2) was designed in this very file but never
  implemented — found via real pre-existing data (2 already-succeeded edit
  runs whose prior-revision comments were still incorrectly `open`), fixed,
  and the real data backfilled using the same query the new code runs.
- Inspiration image files were tracked on every request but never fetched
  into a sandbox — fixed as a full feature: a third per-tenant Storage
  bucket, a real composer UI to select from a tenant's own library, and
  hydration that fetches exactly the selected files (a `.MISSING.txt`
  placeholder for anything that doesn't resolve, never a silent skip).

**Brand data (real inconsistencies found, resolution rule applied, never
adjudicated):**
- Emplifi: `DESIGN.md` vs `tokens.json` disagreed on secondary color, corner
  radius, and h1 size — `DESIGN.md` wins, per its own resolution order.
- Emplifi's `asset_manifest.json` contained an asset stamped with a *different
  brand's* `brand_kit_id` — filtered out by kit id, never used.
- Kahua's `DESIGN.md` disagreed with **itself**: its type-scale table said
  `h1: 56px`, its own "Applying it" prose said `48px` with an explicit
  fallback rule ("cut the copy, don't scale the type"). Resolved in favor of
  the more specific, operational instruction — the same posture as the
  cross-file conflicts, just a same-file instance of it.
- Kahua's manifest referenced a reverse-logo file that doesn't exist — omitted
  per the missing-asset rule, never substituted.
- A full audit (every eyebrow/headline/subhead/CTA in every real render,
  checked against its brand's exact stated numbers) found real type-scale
  violations that had survived one full "look at it" pass each — caught only
  by a second, targeted pass against the source document, not general visual
  review. Fixed and re-rendered.

**Generalization test:** Duolingo (self-built, deliberately incomplete data —
no logo, since the real trademark is unlicensable) went through the exact
same tooling with zero code changes and produced a genuinely different
creative treatment. Patagonia was later onboarded mid-build, live, also with
zero code changes, closer to the brief's actual "hand you a brain you've
never seen" test than Duolingo (which was seen coming).

---

## 7. Disqualifier compliance (ROADMAP.md §1)

No violation found in the current code, traced line-by-level rather than
asserted:

1. **Nothing but the agent moves work out of the sandbox** — the orchestrator
   only checks that `RESULT.json` exists in Storage after a run
   (`execute_run.py`), it never reads the sandbox's filesystem. Saving
   happens from inside the box, via the agent's own signed-URL upload tool.
2. **No tenant/task-specific sandbox identity** — `sandbox_factory.py`'s
   `create_sandbox()` structurally cannot accept a `metadata`/`envs` kwarg at
   creation time; the only per-run data reaching a sandbox is injected at
   command-execution time (API keys), never identity. Brand data is
   re-fetched fresh from Postgres/Storage on every single call.
3. **Agent never runs as a backend subprocess** — the orchestrator's only
   relationship to the agent is an E2B API call that executes inside the
   sandbox's own process space. The frontend's API routes never touch
   E2B/Anthropic/OpenAI at all — confirmed by reading every handler.
4. **No agent on a developer laptop** — the agent's own process (the Claude
   Agent SDK loop) always executes inside the remote E2B sandbox, regardless
   of where the orchestrator client issuing the API call happens to run.
5. **No work exists only on a box** — live-verified via the real mid-run kill
   + resume test (§6); hydration is a pure function of ids, so replay always
   works.
6. **No hardcoded ordering** — `claim_next_run()` claims strictly oldest-
   queued-first with no tenant-aware logic; real concurrent batches (§6) let
   the dispatcher, not the test, decide execution order.

Also checked and held: no automated brand-conformance grader (only
deterministic structural checks plus the mandatory human/agent "look at it"
step — the leak-detection content check is a different, literal-string
category, not a quality score); no edit-routing classifier (left entirely to
the agent's judgment); no brand-kit versioning UI, custom scheduler beyond
capped FIFO, or credential permission system.
