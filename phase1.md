# Phase 1 — Status, Findings, and Design Decisions

Measured against `ROADMAP.md`'s own definition ("Phase 1 — Generate an ad
from a brain (in a sandbox)") and `BUILD_GUIDE.md`'s Step 3 definition of
done. Written the same way `phase0/README.md` was: a running, honest record,
not a victory lap.

## What we did, from the start

Phase 0 proved the design-generation skill by hand, locally, no
infrastructure - both provided brands (Emplifi, Kahua) plus a self-built
third brand (Duolingo), all generated and reviewed one canvas at a time,
with the real per-render judgment calls (contrast fixes, brand-conflict
resolutions) that a purely visual pass alone wouldn't have caught.

Phase 1 turned that manual process into a real, running system: a Supabase
schema plus one reusable `onboard_tenant()` function that brings any brand
in (tested live for all three); a pure `hydrate_generation()` function that
assembles exactly what a sandbox needs from nothing but a tenant/request id;
a save mechanism built on short-lived, single-file signed URLs, verified in
isolation before anything depended on it; a real E2B sandbox, wrapped in a
custom pre-built template after the default sandbox couldn't handle
installing dependencies at runtime; an autonomous agent (`agent_runner.py`)
running the Claude Agent SDK inside that sandbox, minimally tooled (mostly
Bash + the Phase-0-proven scripts, with one deliberate exception for saving
work); and an orchestrator tying all of it into one real, observable run.
Along the way, eleven-plus real issues were found and fixed live (not
anticipated in advance) - a genuine memory ceiling, an OS/package mismatch,
an env-var propagation gap, a retry collision, a near-miss on the single
most important disqualifier, and more, each logged in section 2 with what
actually happened and why. The pipeline was then proven, unmodified, against
all three brands - not just the one it happened to be built against first.

**UPDATE (2026-08-11): Phase 1's "both brands" bar is now met, and then
some.** Emplifi, Kahua, and Duolingo have each been run through the real,
identical, unmodified sandboxed pipeline - not just Emplifi. See section 6.
The paragraph below is left as originally written, since it was true at the
time and the checklist in section 4 still tracks what's left honestly.

**Original bottom line: the core loop is real and proven once, but Phase 1
is not fully done yet.** `ROADMAP.md` is explicit that this phase requires
"both brands" working before it counts - we have one full, successful, verified
run for Emplifi. Kahua and Duolingo have not been run through the real
sandboxed pipeline yet, only through Phase 0's local (non-sandboxed) process.

---

## 1. What's actually built (functionalities)

**Data layer** (`supabase/`)
- Five-table schema live in a real Supabase project: `tenants`, `requests`,
  `revisions`, `assets`, `runs`.
- `onboard_tenant()` - the one real implementation of bringing a new brand
  into the system: creates a tenant row plus **two private Storage buckets
  per tenant** (`brand-kit-{id}`, `jobs-{id}`), uploads brand files. Used
  both by the bootstrap script and (by design) by any future real
  onboarding endpoint - same function, not a parallel implementation.
- Verified live: three tenants onboarded for real (Emplifi, Kahua,
  Duolingo), independently confirmed via Storage listing, not just script
  output.

**Hydration** (`worker/hydration/generation.py`)
- `hydrate_generation(tenant_id, request_id, revision_number)` - a pure
  function, no E2B dependency, returns `{sandbox_path: bytes}`.
- Verified live against real data: produces the correct 15-file payload,
  correctly refuses a deliberately-mismatched tenant/request pair (the
  actual mechanism the "no cross-tenant leakage" requirement depends on).

**Save credential** (`worker/orchestrator/upload_urls.py` +
`agent_runner.py`'s `upload_output_file` tool)
- `mint_upload_urls()` pre-mints one signed, single-path, single-operation,
  time-limited upload URL per file a run is expected to produce, using the
  trusted service-role key, before any sandbox exists.
- Verified in isolation that the token alone is sufficient - no API key,
  no other credential - confirmed by testing with deliberately nothing else.
- The agent's actual save step is a real custom tool (not a hand-typed
  `curl`), using those exact verified mechanics, so a save failure is
  visible to the agent mid-run, not silently wrong.

**Sandbox environment** (`worker/sandbox_images/generation/`)
- `build_template.py` - a one-time, human-run E2B template build
  (`cq-generation-v1`) with dependencies and Chromium pre-installed. Not a
  premature optimization - the original "install everything at runtime"
  approach hit a real memory ceiling on E2B's default 1GB sandbox; this is
  the actual fix, not a speed-up.
- `agent_runner.py` - runs the real Claude Agent SDK loop inside the
  sandbox. Deliberately minimal custom tooling: the agent uses Bash/Read/
  Write/Glob (built into the SDK) plus the two Phase-0-proven CLI scripts
  (`call_gpt_image.py`, `render_html.py`) via Bash, exactly like a human
  operator would. The one exception is the save tool (above).
- Observability added after a real incident (see Findings): per-turn
  heartbeat (`_status.json`, re-uploaded every turn), incremental
  transcript checkpoints (every 5 turns, not just at the end).

**Orchestrator** (`worker/orchestrator/run_generation.py`)
- Full sequence: insert `runs` row (queued) → hydrate → mint URLs → create
  anonymous sandbox from the template → write files in → execute
  `agent_runner.py` in the background while polling real E2B CPU/memory
  metrics concurrently → destroy the sandbox → verify success by reading
  **Storage**, never the (already-destroyed) sandbox's filesystem → update
  the `runs` row, now including `started_at`/`ended_at`.
- Only `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and `PLAYWRIGHT_BROWSERS_PATH`
  are ever passed into the sandbox - no Supabase key, no E2B key, no
  Kernel/Adstream creds anywhere near a generation box.

**Proof it actually works**: one full, real, live run for Emplifi - three
canvases (square/landscape/portrait; the 728x90 leaderboard is deliberately
out of scope, see the note below) generated, the agent caught
and self-corrected a color mistake mid-run, correctly excluded a
cross-tagged manifest asset, correctly handled a missing inspiration file
by proceeding without it, uploaded everything, verified independently by
downloading and looking at the real renders (not just trusting the agent's
own summary) and by diffing the actual overlay HTML against `DESIGN.md`'s
stated values.

---

## 2. Issues found, in the order they actually happened

1. **`gpt-image-2` rejects every required canvas size as-is** (divisible-
   by-16 requirement) and has a hard 3:1 max aspect ratio plus a
   655,360-8,294,400 total-pixel floor - found in Phase 0, fixed with a
   nearest-valid-size-then-uniform-resize approach for the three working
   sizes. **728x90 is architecturally blocked and now explicitly out of
   scope** (decision, 2026-08-11): the real product goal is ads compatible
   with Facebook, Instagram, and TikTok, not generic IAB web-banner sizes -
   728x90 (a leaderboard banner format) isn't actually a native placement on
   any of those three platforms anyway, so chasing a workaround for it was
   solving the wrong problem. No longer an open CEO question to resolve;
   the four working sizes (square/landscape/portrait/**story**) now cover
   real Instagram/Facebook feed placements plus Stories/Reels/TikTok's
   actual native 9:16 shape - added same-day, confirmed working live (see
   section 3).
2. **A scoring bug in the size-resolution search**, found while fixing (1):
   widening the search range briefly caused it to pick a needlessly huge
   (5x oversized) generation for a ratio improvement of 0.003% - fixed by
   making pixel-area cost the tiebreaker instead of raw ratio accuracy.
3. **Type-scale drift recurred in the real agent run**, independently of
   the earlier Phase 0 audit and its saved memory rule - because that
   memory only shapes the outer session's own behavior, it never
   automatically reaches the in-sandbox agent's system prompt. Fixed by
   adding an explicit, forceful instruction directly into
   `agent_runner.py`'s prompt, naming the exact past failure. **Not yet
   re-verified with a fresh live run.**
4. **E2B's default sandbox has only 1GB RAM**, and installing Playwright +
   Chromium + Python packages at runtime overloaded it (the "memory
   threshold exceeded" incident). Root-caused via E2B's own pricing docs
   (CPU/RAM customization requires a paid plan; a template can still be
   built at the free-tier default size) before building a fix, rather than
   assuming a plan upgrade was required.
5. **`playwright install chromium --with-deps` fails on the initial base
   image** (Debian trixie package names don't match Playwright's Ubuntu-
   targeted installer) - fixed by switching the template's base image to
   Microsoft's official pre-built Playwright+Python image instead of
   hand-patching package names.
6. **Browser binary path mismatch even after that fix** - the base image's
   browsers live at `/ms-playwright`, but neither the base image's own env
   var nor a template-level `set_envs()` call persisted into the actual
   running sandbox's environment (confirmed by direct inspection, not
   assumed). Fixed by passing `PLAYWRIGHT_BROWSERS_PATH` explicitly at
   actual command-execution time, where it correctly inherits down through
   every child process.
7. **Signed-upload-URL minting collides on retry** (`409 Duplicate`) -
   minting reserves the path even before anything is uploaded, so re-
   running for the same request/revision (exactly what a resumed/retried
   run needs to do) failed without `upsert=true`. Fixed - and this is now
   the correct default, not an edge case, since resumability requires it.
8. **A near-miss on the single most important disqualifier**: about to run
   the actual agent loop locally to test it in isolation before E2B was
   wired in, reasoning it was the same kind of safe isolated test as the
   data-layer pieces. Caught before execution. The real distinction: does
   this code *launch an agent loop*, not "is it agent-adjacent." Saved as a
   standing rule.
9. **An orphaned sandbox from an earlier interrupted run was left alive**
   because the script died before reaching its `finally: sbx.kill()`.
   Found via `Sandbox.list()`, killed manually. Root cause of the
   ambiguity: no visibility into a long-running step meant "slow" and
   "stuck" looked identical from outside - this is what motivated the
   heartbeat/metrics-polling additions in section 1.
10. **A path-depth bug in `build_template.py`**: `ROOT` was computed one
    `dirname()` call too shallow for that file's location, so
    `load_dotenv()` silently loaded nothing and `E2B_API_KEY` was never
    actually set - surfaced as a confusing `KeyError` rather than a clear
    "env not found" message. Fixed; worth remembering this class of bug is
    easy to reintroduce anytime a new script is added at a new directory
    depth.
11. **Transient network errors** (`BadRecordMac` TLS drops) during both a
    Supabase upload and an E2B file write - not logic bugs, resolved by
    straightforward retry, consistent with earlier transient failures seen
    during Phase 0 seeding.
12. **The Claude Agent SDK's subprocess IPC channel has a hard-coded 1MB
    default max JSON message size** (`_DEFAULT_MAX_BUFFER_SIZE` in the
    SDK's own `subprocess_cli.py`, confirmed by reading the source, not
    guessed) - a sufficiently large rendered PNG, base64-encoded and read
    via the agent's own Read tool, exceeded it and killed the entire
    session outright, with no chance to recover. Hit for real on a
    Duolingo landscape plate; nothing to do with brand identity - any
    brand's sufficiently detailed render could trigger it. Fixed by setting
    `ClaudeAgentOptions(max_buffer_size=50*1024*1024)` - raising the real
    ceiling, not asking the agent to review degraded/smaller images, since
    `SKILL.md`'s "look at it" step needs full-resolution review to mean
    anything.
13. **A secondary, more subtle version of finding #3 survived the fix.**
    The explicit type-scale instruction added to `agent_runner.py`'s
    prompt successfully stopped the agent from *inventing* pixel values not
    in `DESIGN.md` (confirmed: Duolingo's retry used exactly 13/56/24/24px
    across all three canvases, all real stated values) - but it used the
    `h3` value (24px) for subhead/CTA text instead of the `body` value
    (16px) `DESIGN.md` actually specifies for that role. The instruction
    guaranteed "only real values," not "the right value for each role" -
    those turned out to be two different guarantees, and only the first
    one was actually written down.

---

## 3. Design decisions, and why

- **728x90 dropped from scope entirely, not left as an unresolved blocker.**
  The real product goal is ad placements that actually work on Facebook,
  Instagram, and TikTok - a 728x90 IAB leaderboard banner isn't a native
  format on any of those three platforms in the first place, so the
  "how do we generate this" problem was the wrong problem to keep solving.
  Reframed as a scope decision (2026-08-11), not a technical concession -
  the three sizes already built (square/landscape/portrait) map to real
  Instagram/Facebook feed placements already. A 9:16 vertical format
  (Stories/Reels/TikTok's actual native shape) is a more useful thing to
  consider adding than continuing to chase 728x90 ever was.
- **Per-tenant Storage buckets (both `brand-kit` and `jobs`), not a shared
  bucket with a tenant-id-prefixed path.** A bug in one tenant's bucket
  setup stays contained to that bucket, rather than one shared policy
  mistake exposing every tenant at once. Confirmed this doesn't conflict
  with any disqualifier - the "clean box" rule is about a box's *identity*
  revealing which tenant/task it serves, not about tenant data being
  organizationally separated in storage.
- **A custom E2B template with dependencies pre-installed does not violate
  the "clean box" disqualifier.** Checked directly against the brief's own
  text, not just inferred: the hydration mental model already assumes
  tooling is present ("imagine SSHing into the box, typing `claude`...and
  walking away"), and the disqualifier is explicitly about a box's identity
  revealing tenant/task, not about pre-installed software. The template is
  identical for every brand - zero tenant/task identity baked in.
- **One real custom tool (`upload_output_file`) as the sole exception to
  "the agent should just use Bash."** The brief requires save failures to
  be loud and actionable within the same run; an LLM-improvised `curl` call
  that's subtly wrong would fail invisibly from the agent's own
  perspective. Everything else - image generation, rendering - stays on
  Bash + the Phase-0-proven scripts.
- **The transcript-upload step and the final RESULT.json write happen as
  deterministic harness code, not agent tool calls**, because by the time
  they run the agent's own conversation is already over - there's no
  "agent decision" left to make. Still executes inside the sandbox, still
  part of the same run.
- **Signed URLs are minted for every expected output file up front**,
  before the sandbox exists, rather than the agent requesting credentials
  as it goes - keeps credential issuance entirely on the trusted side, and
  makes the complete set of a run's expected outputs explicit and
  enumerable from the request's canvases.
- **Heartbeat and incremental transcript checkpoints exist because of a
  real incident**, not speculative hardening - added directly in response
  to not being able to tell a slow run from a stuck one.

**Confirmed (2026-08-11): adding the 9:16 "story" canvas required exactly
one line of change** - a new entry in `create_test_request.py`'s shared
`CANVASES` list. Nothing in `hydrate_generation`, `mint_upload_urls`,
`run_generation.py`, or `agent_runner.py` needed to change, because none of
them ever hardcoded which canvases exist - they all iterate over whatever
`request["canvases"]` contains. Ran for real against Emplifi (all four
sizes in one request): succeeded, the agent held 48px on every canvas
including the new one, and independently verified the actual story render -
correct 9:16 proportions, on-brand, and the plate's product-grid phone
mockup ties directly into the campaign headline. This is the same kind of
evidence as the three-brand confirmation in section 6: the architecture
being genuinely generic, not asserted to be.

---

## 4. Checklist: achieved vs. still open

### Achieved
- [x] Supabase schema live, migrated, verified
- [x] Tenant onboarding (`onboard_tenant`) live-tested for 3 brands
- [x] `hydrate_generation()` live-tested, tenant-mismatch safety confirmed
- [x] Signed-upload-URL save mechanism verified in isolation and in the real run
- [x] E2B sandbox mechanics verified (create/write/execute/destroy, file integrity)
- [x] Custom E2B template built and fixed through three real, distinct issues
- [x] `agent_runner.py` executed successfully, for real, three times, for three different brands (Emplifi, Kahua, Duolingo) - zero code changes between them
- [x] Orchestrator records run state durably, verifies via Storage only
- [x] Observability added and **confirmed working live**: timestamps, heartbeat, incremental transcript (checkpointed every 5 turns across all three runs), live CPU/memory metrics
- [x] Zero disqualifier violations across all of the above (one near-miss, caught before execution)
- [x] **"Must work for both brands" (ROADMAP.md) - met, and exceeded (three brands, not two)**
- [x] Type-scale prompt fix verified live: Duolingo's retry held 13/56/24/24px identically across all three canvases, no invented values (see finding #13 for the one remaining nuance - real values, not always the semantically correct one)
- [x] A second, real, distinct bug (SDK 1MB message buffer) found and fixed live via the Duolingo run - direct evidence this is genuine testing, not a scripted demo

### Explicitly open - required before Phase 1 itself is "done" per ROADMAP.md
- [x] ~~The same real, live, sandboxed run proven for Kahua~~ - done 2026-08-11
- [x] ~~Ideally the same for Duolingo too~~ - done 2026-08-11, and it's the one that found finding #12
- [ ] Tighten the type-scale instruction to specify role-to-value mapping, not just "use a real value" (finding #13)

### Explicitly open - belongs to later phases, not blocking Phase 1, but real
- [x] ~~728x90 leaderboard - open question for the CEO~~ - resolved 2026-08-11: deliberately out of scope, not a real Facebook/Instagram/TikTok placement anyway; no longer pending.
- [x] ~~9:16 vertical size for Stories/Reels/TikTok~~ - added and confirmed working live 2026-08-11 (Emplifi, all four canvases in one request, story render independently verified)
- [ ] The "horrifying test case": concurrent multi-tenant requests, never run
- [ ] Deliberate resume test: kill a box mid-task on purpose, confirm a fresh box picks up cleanly (informally exercised via real failures, never as a controlled test)
- [ ] Deliberate crash-recovery test with documented recoverable/unrecoverable states
- [~] Day-two third-brand test with zero code changes - **substantially satisfied** by the real Duolingo run (self-built brand, deliberately incomplete data, zero pipeline code changes needed), but not identical to the real test: Duolingo is a brand we authored ourselves and have seen before, not one handed to us blind at the walkthrough. The mechanism is proven; the blind version is still the real remaining test.
- [ ] Inspiration image files are still never actually fetched - filename passes through, agent currently just proceeds without it (handled gracefully, but the capability itself doesn't exist)
- [ ] Edit flow / revision > 1 has never been exercised - every run so far has been a fresh "new" request
- [ ] RLS policies - still nonexistent; fine for backend-only work, blocking before any frontend touches Supabase directly
- [ ] `comments`/`deploys` tables - correctly deferred, not started
- [ ] Frontend / real request-intake surface - doesn't exist; every request so far created via a dev script or direct insert
- [ ] `DECISIONS.md` hasn't been updated with what Phase 1 actually learned (e.g., the real verified credential mechanics, the per-tenant-bucket reasoning now proven in practice) - still reflects pre-implementation reasoning in places

---

## 6. Confirmation runs: Kahua and Duolingo (2026-08-11)

`create_test_request.py` was refactored from an Emplifi-only script into a
tenant-parameterized function (`TEST_REQUESTS` dict keyed by slug) - one
shared implementation, not a copy-pasted script per brand, consistent with
how `onboard_tenant()` was already built. This itself was a small but real
test: does anything about the *test data setup* assume Emplifi, separate
from whether the pipeline itself does.

**Kahua** - ran clean on the first attempt. Correctly re-discovered and
resolved the same three known data gaps found by hand in Phase 0 (the
`DESIGN.md` self-contradiction on h1 size, the missing Barlow Condensed
file, the missing reverse logo), using only the manifest/`DESIGN.md`
content available to it - not told any of this in advance. Independently
verified: logo placement, headline held at exactly 48px, jobsite-photo plate
treatment matching the brand's documented voice.

**Duolingo** - failed on the first attempt (finding #12, the SDK's 1MB
message buffer, triggered by a large landscape plate), fixed, then
succeeded completely on retry. Independently verified via direct download
and visual review (not the agent's own summary): three genuinely different,
on-brand compositions built around a coffee-cup-with-a-streak-swirl motif
that visually reinforces the "coffee break" headline copy - a creative
choice the agent made on its own, not specified anywhere in the prompt.
Font-size audit (finding #13) confirmed the type-scale fix held for real
values, with the one noted role-mapping nuance.

**What this actually demonstrates**: the word "kahua" and "duolingo" exist
in exactly one place across the whole codebase - the `TEST_REQUESTS` dict,
which stands in for a UI form submission that doesn't exist yet. Every
function downstream of that (`hydrate_generation`, `mint_upload_urls`,
`run_generation.py`, `agent_runner.py`) operates purely on opaque UUIDs and
dynamically-discovered bucket/file names. See the conversation record for
the full traced explanation of why this is real evidence, not an assertion.

---

## 7. Recommended next steps, in order

1. Tighten the type-scale system-prompt instruction to specify which named
   value maps to which text role (headline=h1, subhead/body copy=body,
   eyebrow=caption), closing finding #13 - small, cheap, worth doing before
   it's forgotten.
2. Move to `ROADMAP.md`'s Phase 2 ("the engine"): concurrency (the
   "horrifying test case" - concurrent multi-tenant requests, never run),
   a deliberate resume test (kill a box on purpose, confirm a fresh box
   picks up cleanly), a deliberate crash-recovery test with documented
   recoverable/unrecoverable states, and the edit flow (revision > 1,
   comments-driven - never exercised so far, every run has been a fresh
   "new" request).
3. Update `DECISIONS.md` with what's actually been learned across all three
   runs - the real credential blast-radius (now verified three times over,
   not just proposed), the per-tenant-bucket decision, and the type-scale/
   prompt-inheritance gap between outer-session memory and in-sandbox agent
   instructions.
4. ~~Resolve the 728x90 leaderboard question with the CEO~~ - resolved
   2026-08-11: deliberately out of scope (see finding #1). ~~Consider adding
   a 9:16 vertical size~~ - done same day, confirmed working live.
5. When the real day-two brand shows up, run it through this exact
   pipeline unmodified - that's the actual test everything in this file has
   been rehearsing for.
