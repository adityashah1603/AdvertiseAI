# Phase 1 — Status, Findings, and Design Decisions

Measured against `ROADMAP.md`'s "Phase 1 — Generate an ad from a brain (in
a sandbox)" and Phase 2 ("the engine"). Both are now substantially done:
all three brands run live through the real sandboxed pipeline, the
concurrency cap + leak-proof test, the edit flow, and the deliberate
resume/crash-recovery tests have all been run for real and verified
against Storage/DB, not just agent self-reports.

---

## 1. What's built

- **Data layer** (`supabase/`): 5-table schema (`tenants`, `requests`,
  `revisions`, `assets`, `runs`) + `comments` (added for edits). One
  `onboard_tenant()` function creates a tenant + two private per-tenant
  Storage buckets (`brand-kit-{id}`, `jobs-{id}`). Live-tested for 3
  tenants (Emplifi, Kahua, Duolingo).
- **Hydration** (`worker/hydration/generation.py`): pure function
  `hydrate_generation(tenant_id, request_id, revision_number)` →
  `{sandbox_path: bytes}`. Refuses a mismatched tenant/request pair (the
  actual no-cross-tenant-leakage mechanism). Extended (not forked) to pull
  in a prior revision's assets + open comments for edits.
- **Save credential** (`upload_urls.py` + `agent_runner.py`'s
  `upload_output_file` tool): one short-lived, single-path signed URL per
  expected output file, minted before the sandbox exists. The agent's only
  custom tool — every other action is Bash + the Phase-0-proven scripts.
- **Sandbox** (`worker/sandbox_images/generation/`): custom pre-built E2B
  template (`cq-generation-v1`, deps + Chromium preinstalled — required,
  not an optimization). `agent_runner.py` runs the real Claude Agent SDK
  loop inside it; per-turn heartbeat + incremental transcript checkpoints.
- **Orchestrator**: `enqueue.py` (insert queued run) → `dispatcher.py`
  (capped `ThreadPoolExecutor` polling a race-safe `claim_next_run()`
  Postgres function) → `execute_run.py` (hydrate → mint URLs → sandbox →
  run agent → destroy → verify via **Storage**, never the dead sandbox →
  update `runs`/`revisions`). Only `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/
  `PLAYWRIGHT_BROWSERS_PATH` ever reach a generation box.

---

## 2. Issues found and fixed

1. `gpt-image-2` rejects target sizes as-is (÷16 requirement, 3:1 max
   ratio, pixel-count floor) → nearest-valid-size + uniform resize.
   728×90 is architecturally blocked *and* not a real FB/IG/TikTok
   placement → dropped from scope entirely; added a 9:16 "story" size
   instead (real Stories/Reels/TikTok shape).
2. Size-search picked a needlessly 5×-oversized generation for a 0.003%
   ratio gain → pixel-area cost added as tiebreaker.
3. Type-scale drift in the real agent run (outer-session memory doesn't
   reach the in-sandbox prompt) → explicit type-scale instruction added
   directly to `agent_runner.py`'s prompt.
4. E2B's default 1GB sandbox OOM'd installing deps at runtime → pre-built
   custom template instead.
5. `playwright install --with-deps` fails on the base image (Debian
   trixie vs. Ubuntu package names) → switched to Microsoft's prebuilt
   Playwright+Python base image.
6. Browser path env var didn't persist into the running sandbox → pass
   `PLAYWRIGHT_BROWSERS_PATH` explicitly at command-execution time.
7. Signed-upload-URL minting collides on retry (`409 Duplicate`) →
   `upsert=true` by default (retries need this by construction).
8. Near-miss: about to run the actual agent loop locally to "test it in
   isolation" → caught before execution. Standing rule: never run an
   agent loop outside the real sandbox, full stop.
9. Orphaned sandbox left alive (script died before `finally: sbx.kill()`)
   → found via `Sandbox.list()`, killed manually; motivated the
   heartbeat/metrics additions (no way to tell "slow" from "stuck").
10. `build_template.py` computed its `.env` path one directory too
    shallow → `E2B_API_KEY` silently never set → fixed path depth.
11. Transient `BadRecordMac` TLS drops on Supabase/E2B calls → resolved
    with retry.
12. Claude Agent SDK's subprocess IPC has a hard 1MB default max message
    size → a large rendered PNG read via the agent's own Read tool killed
    the session outright → `max_buffer_size=50MB`.
13. The type-scale fix (#3) stopped invented values but still used the
    wrong *role* mapping (h3 instead of body for subhead/CTA) → prompt now
    states an explicit role→value mapping and names the exact past
    mistake.
14. PostgREST served a stale cached schema after a migration
    (`runs.revision_number`) → `NOTIFY pgrst, 'reload schema';`.
15. Two zombie `running` rows (leftover from #9's manual kill, which never
    told Postgres) silently occupied both concurrency-cap slots forever →
    corrected by hand. Real evidence: a `running` row with a dead sandbox
    does **not** self-heal on retry — no automatic staleness detection
    exists yet (not built, not required by ROADMAP).
16. Leak-detection check had a false positive on a legitimate `<br/>` tag
    inside real headline text → strip HTML tags before comparing.
17. A real successful run was misreported `failed` — Windows' console
    codepage crashed on a non-ASCII character in the orchestrator's own
    log line, caught by that run's broad except-and-mark-failed block →
    reconfigured stdout/stderr to UTF-8 with `errors="replace"`.
18. `BadRecordMac` recurred specifically inside the per-file sandbox-write
    loop (3 different files, 3 different runs) → bounded 3-attempt retry
    around each individual `sbx.files.write()` call.
19. `execute_run.py` never touched the `revisions` table — successful runs
    left `runs.revision_id` null and `revisions.status` stuck `pending`
    forever → now updates the existing `revisions` row to `generating` on
    start and `ready`/`failed` (+ links `run_id`/`revision_id` both ways)
    on completion. Verified live: before the fix, `pending`/`null`
    survived two full successes; after, one real run left it
    `ready`/correctly cross-linked.

---

## 3. Design decisions

- **728×90 dropped from scope** — not a native FB/IG/TikTok placement
  anyway; a 9:16 story size was added instead and is more useful.
- **Per-tenant Storage buckets**, not a shared bucket with a prefix — one
  tenant's bucket-policy bug stays contained. Doesn't conflict with the
  "clean box" disqualifier (that's about sandbox *identity*, not data
  organization).
- **Custom E2B template with deps preinstalled is not a disqualifier
  violation** — checked directly against the brief's own hydration model,
  which already assumes tooling is present; identical for every brand,
  zero tenant/task identity baked in.
- **One real custom tool (`upload_output_file`)** as the sole exception to
  "the agent uses Bash" — a save failure must be loud to the agent, and an
  improvised `curl` call could fail silently from its perspective.
- **Signed URLs minted for every expected output file up front**, before
  the sandbox exists — keeps credential issuance entirely on the trusted
  side.
- **Heartbeat + incremental transcript checkpoints** exist because of a
  real "can't tell slow from stuck" incident, not speculative hardening.
- **Adding a new canvas size is a one-line change** (a new entry in
  `create_test_request.py`'s `CANVASES` list) — nothing downstream
  hardcodes which canvases exist. Verified live (the 9:16 story size).

---

## 4. Checklist

### Achieved
- [x] Supabase schema live, migrated, verified
- [x] Tenant onboarding live-tested for 3 brands
- [x] Hydration live-tested, tenant-mismatch safety confirmed
- [x] Signed-upload-URL save mechanism verified in isolation and live
- [x] E2B sandbox mechanics verified (create/write/execute/destroy)
- [x] Custom E2B template built and fixed through 3 real issues
- [x] `agent_runner.py` run successfully for 3 brands, zero code changes
      between them
- [x] Orchestrator records run state durably, verifies via Storage only
- [x] Observability confirmed working live (heartbeat, checkpointed
      transcript, live CPU/mem metrics)
- [x] Zero disqualifier violations (one near-miss, caught pre-execution)
- [x] "Both brands" requirement met and exceeded (3 brands)
- [x] Type-scale prompt fix verified live (role-mapping nuance closed —
      finding #13)
- [x] Concurrency cap + horrifying-test-case (new-requests half): cap
      proven exactly respected, zero cross-tenant/cross-job leakage across
      4 real concurrent runs
- [x] Edit flow: 2 real edit runs — one correctly rejected inaccurate
      feedback (byte-identical output), one applied a real targeted
      change leaving the plate byte-identical
- [x] Deliberate resume test — real `Sandbox.kill()` mid-run, plain
      re-enqueue of the same revision completed cleanly with no
      awareness of the prior kill
- [x] Deliberate crash-recovery test — killed after billed image-gen
      succeeded but before save completed; documented exactly what's
      saved vs. lost; confirmed re-billing is **not** avoided (matches
      ROADMAP's "nice to have, not mandatory")
- [x] `revisions` table linking gap — found and fixed (#19)

### Still open
- [~] Day-two third-brand test with zero code changes — substantially
  satisfied by the real Duolingo run (self-built, deliberately incomplete
  data, zero pipeline changes needed), but not identical: Duolingo is a
  brand we've seen before, not one handed to us blind.
- [ ] Inspiration image files are never actually fetched — filename
  passes through, agent proceeds without it.
- [ ] Comment `status` transitions (resolved/stale/orphaned) unbuilt —
  comments stay `open` forever.
- [ ] The edit half of the horrifying concurrency test (concurrent edits
  across tenants) is unblocked but not yet run as its own test.
- [ ] Automatic staleness detection for a `running` row with no live
  sandbox behind it (gap from finding #15) — not required by ROADMAP, but
  now demonstrated to actually happen.
- [ ] RLS policies — nonexistent; fine backend-only, blocks any frontend
  touching Supabase directly.
- [ ] Frontend / real request-intake surface — doesn't exist yet.
- [ ] `DECISIONS.md` not yet updated with what Phase 1/2 actually proved.

---

## 5. Concurrency test results (`ROADMAP.md` §5)

Built: `claim_next_run()` Postgres function (locks a sentinel row `FOR
UPDATE`, counts `running` fresh from truth, claims oldest `queued` via
`SKIP LOCKED` — race-safe by construction) behind a capped
`ThreadPoolExecutor` dispatcher. Leak-detection canary proven capable of
catching a real leak before being trusted (per ROADMAP's explicit
instruction) — caught a real bug in itself in the process (#16).

Real test, cap=2, 4 concurrent requests (2 Emplifi campaigns, 1 Kahua, 1
Duolingo): all 4 succeeded; peak concurrently-`running` count, computed by
interval-overlap analysis, was exactly 2; every output, checked
independently against tag-stripped visible text, contained only its own
headline — including between the two same-tenant Emplifi jobs.

## 6. Edit flow results (`ROADMAP.md` §4.1)

`comments` table added; edit-ness is derived (does `revision_number - 1`
have a succeeded run), not passed in as a flag. Classifying "text patch
vs. full regen" is left entirely to the agent (per ROADMAP, no classifier
built).

Two real edit runs against a real completed Kahua ad: inaccurate feedback
(wrong CTA color, mispositioned comment) was correctly rejected — output
byte-identical, verified by SHA-256; accurate feedback (a real CTA-label
change) was applied exactly, with the plate byte-identical and only the
targeted overlay text changed.

## 7. Resume + crash-recovery test results (`ROADMAP.md` §6)

Getting a kill to land mid-run (not before, not after) took real spend —
6 failed attempts trying to trigger the kill off buffered stdout, which
turned out to lag real execution unpredictably. Fixed by watching
**Storage** directly for `plate.png` landing at its real path (a verified
fact, not a log line) and killing the instant it appeared.

Result: `plate.png` + `overlay.html` (and mid-run transcript/status
checkpoints) were saved before the kill; `render.png`/`RESULT.json` were
not. The run was automatically marked `failed` with a clear error message
(`execute_run.py`'s own exception handling caught it — no stuck `running`
row). A plain re-enqueue of the same revision, no special-casing, spun up
a fresh sandbox and completed successfully.

- **What a plain retry recovers automatically:** everything, in this
  design — hydration is a pure function of ids, so replay just works.
- **What needs a human:** nothing in *this* failure mode (kill caught by
  `execute_run.py`'s own exception handler). The scenario that does need a
  human is finding #15 — a sandbox killed *outside* that code path leaves
  a `running` row that never self-heals.
- **Re-billing:** not avoided (confirmed — the retry made a second real,
  differently-sized image-gen call rather than reusing the already-saved
  plate). Matches ROADMAP's explicit "nice to have, not mandatory."

This test also surfaced finding #19 (the `revisions` linking gap), now
fixed.

---

## 8. Recommended next steps

1. Consider automatic staleness detection for a `running` row with no live
   sandbox (finding #15's gap) — not required, now demonstrated real.
2. Update `DECISIONS.md` with what Phase 1/2 actually proved (credential
   blast-radius, per-tenant-bucket reasoning, concurrency-cap design,
   resume/crash-recovery findings).
3. Run the edit half of the horrifying concurrency test (concurrent edits
   across tenants) — unblocked, not yet run.
4. When the real day-two brand shows up, run it through this exact
   pipeline unmodified — the actual test everything above has rehearsed
   for.
