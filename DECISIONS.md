# DECISIONS.md

Write-up accompanying the code. Positions, not features — no version graphs, diffing, or permission systems built for §4.

---

## 1. Built vs. stubbed

| Area | Status | Note |
|---|---|---|
| Phase 0 — local skill gate | done | 20+ ads, Emplifi/Kahua/Duolingo, local, no sandbox |
| Phase 1 — generation pipeline | done | 4 brands live through real sandbox path, zero code changes per brand |
| Phase 2 — engine | done | Concurrency, resume, crash-recovery all proven live, not asserted |
| Phase 3 — feedback surface | done | Pinned comments, drag-to-pin UI, resolved-status all live |
| Phase 4 — deployment | not started | No sandbox image, no hydrate_deploy, no Adstream, no deploys table |

Stubbed by choice: brand-kit versioning, conformance grader, edit-routing classifier, scheduler beyond FIFO, credential permission system.

---

## 2. Next steps

- Build Part 4 (Deploy) — same hydrate/sandbox/save/destroy shape + browser + Adstream creds + detail-page read-back.
- One dispatcher process per env, or matching caps — mixed caps let peak exceed the lower one (found live).
- Pin every venv's deps — orchestrator had none, silently drifted e2b versions, broke sandbox creation twice.
- Re-billing on retry not avoided — nice-to-have per brief, not fixed.
- RLS still unbuilt — harmless today (server-only access), revisit if client-side Supabase access is ever added.
- Re-run 4-tenant concurrent edit test — last clean run only had 2 tenants eligible.
- Write top-level README.md — venv-per-script ambiguity caused a real outage.

---

## 3. Storage / hydration / resume model

- Three tiers, kept separate everywhere: **global** (skill, tooling — same every run), **tenant** (brand kit — fetched fresh every run, never cached), **job** (request/copy/comments/revisions — unique per run).
- `hydrate_generation(tenant_id, request_id, revision_number)` — pure function, no side effects, no sandbox awareness. Same inputs → same files, always.
- Resume = replay. Killing a box and rehydrating the same ids into a new one is the whole recovery story — no snapshot, no diff engine. Proven live (§6).
- Per-tenant Storage buckets (brand kit, jobs, inspirations) — isolation boundary is the bucket, not a path prefix.

---

## 4. The four questions

### 4.1 Brand changes between revision 3 and 6
Position: never freeze a brand kit to a task — always fetch fresh. Fingerprint-diff-and-surface (not block) is the cheap fix, not yet built.
Least sure: whether non-blocking is enough for a real operator.

### 4.2 Stale pinned comment
Position: `open` → `resolved` (edit run against it succeeded, built + verified) → `orphaned` (newer revision exists, nothing closed it, deliberately unbuilt — brief says don't).
No coordinate remapping, no pixel diffing, ever.

### 4.3 Concurrency cap + the 4th request
Position: env-var cap per run-type, Postgres row-lock (`claim_next_run`) enforces it, excess sits `queued` FIFO, visible in UI.
Real nuance: cap is per-caller, not global — two dispatchers with different caps can jointly exceed the lower one.

### 4.4 Credential blast radius
Generation sandbox: OpenAI + Anthropic keys, per-file signed upload URLs only — no DB key, no other tenant's data, no Adstream.
Deploy sandbox (not built): Adstream login + Kernel key only, no OpenAI key, no brand-kit access.

---

## 5. Least sure of

- Fingerprint-diff-and-surface (4.1) may not be enough for a real operator workflow.
- Silent orphaning (4.2) may lose real feedback vs. an explicit re-raise prompt.
- FIFO, zero per-tenant fairness (4.3) — fine at trial scale, untested at real volume.
- One shared Adstream login standing in for per-tenant creds (4.4) — aspirational once Part 4 exists.
- Day-two brand test: Duolingo + Patagonia both zero-code-change, but both self-onboarded, not handed over cold.
- 2-tenant concurrent-edit proof, not 4 — other two dropped out from an earlier failed attempt.
- No full second "look at it" pass across every render — only spot audits caught the type-scale violations in §6.

**Transparency note:** Phase 0 saw `.gitignore` edited to re-hide ROADMAP/DECISIONS with an instruction not to mention it. Flagged to the user then, not complied with. Not recurred since.

---

## 6. Key findings

- `gpt-image-2`: real bounds are ÷16 edges, ≤3840px, ≤3:1 ratio, 655K–8.3M px. 728×90 impossible — dropped, documented, replaced with 9:16 story.
- Type-scale role mistakes (wrong named value, or scaling type to fit) — recurred across brands, fixed via explicit prompt rule, not a validator.
- Default 1GB sandbox OOM'd on deps → custom pre-built template. Zero tenant identity in it — checked against disqualifier #2.
- `Sandbox.create` broke twice, opposite directions: e2b 1.0.5 lacked it, e2b 2.38.0 (unpinned drift) required it again. Fixed + pinned.
- Multi-process cap nuance (§2) — found live, re-run with one process confirmed cap holds.
- Concurrent batch (cap=2, 4 reqs/3 tenants): peak exactly 2, zero leakage. Leak-checker proven able to catch a planted leak first.
- Mid-run `Sandbox.kill()` + re-enqueue: resumed clean, agent unaware. Re-billing on retry not avoided.
- Stuck `running` row (sandbox died outside normal exception path) doesn't self-heal alone — fixed, now expires after 20 min.
- `revisions` table was never updated on success — silent gap, found via real orphaned-revision audit, fixed.
- Comment `resolved` was designed here but never coded — found via real stale data, fixed, backfilled.
- Inspirations were tracked but never fetched — full fix: per-tenant bucket, real picker UI, hydration fetch.
- Brand data: Emplifi DESIGN.md vs tokens.json disagree (DESIGN.md wins); Kahua's own DESIGN.md self-contradicts (56px table vs 48px prose — prose wins, more operational); missing assets omitted, never faked.

---

## 7. Disqualifier compliance (docx brief / ROADMAP §1 / SKILL.md)

- Nothing but the agent moves work out of the box — orchestrator only checks Storage after, never reads the sandbox.
- No tenant/task sandbox identity — `create_sandbox()` can't accept metadata/envs at creation; brand data re-fetched fresh every run.
- Agent never a backend subprocess — runs inside E2B only, reached via API; frontend never touches E2B/Anthropic/OpenAI.
- No agent on a laptop — the agent's own process always executes inside the remote sandbox.
- No work exists only on a box — hydration is a pure function of ids; live kill+resume test proves it.
- No hardcoded ordering — FIFO claim, no tenant-aware logic; proven under real concurrent load.
- No brand-conformance grader — only deterministic structural checks + mandatory human/agent "look at it."
- No edit-routing classifier — left entirely to the agent, every time.
- SKILL.md invariants (plate-first, one plate per size, every word live HTML, logo natural proportions, DESIGN.md wins, inspirations reference-only, never publish) — held; enforced via agent system prompt + structural checks, never a scoring program.

**Status: zero hard-constraint violations found**, current code, both docs cross-checked.
