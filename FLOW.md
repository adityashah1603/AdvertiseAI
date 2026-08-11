# FLOW.md

How a request actually moves through the system, and what happens in every real scenario that's been hit or tested. Companion to `DECISIONS.md` (the why); this is the what/when.

---

## 1. The one shape everything follows

```
request lands in Postgres (status=queued)
        |
        v
dispatcher.py polls claim_next_run() / claim_next_deploy_run()
        |  (oldest queued wins, cap permitting - pure FIFO, no tenant logic)
        v
hydrate_*(tenant_id, request_id, revision_number)   <- pure function, fresh every time
        |  (fetches global + tenant + job data fresh from Postgres/Storage)
        v
create_sandbox()  -> anonymous E2B box, no tenant/task identity
        |
        v
hydrated files written IN + agent script written IN
        |
        v
agent runs (Claude Agent SDK) - generates/edits/deploys
        |  (uploads each output file itself, via its own signed URL, immediately)
        v
box destroyed
        |
        v
orchestrator reads Storage back (never the dead box) to verify
        |
        v
runs/revisions/deploys rows updated -> succeeded or failed
```

Generate, edit, and deploy are all this exact same loop. Only the hydration inputs and the agent's task differ.

---

## 2. The three flows

### New generation
`POST /api/requests` -> `requests` + `revisions(1, pending)` + `runs(generate, queued)` -> loop above -> `assets` rows + `revisions.status=ready`.

### Edit
`POST /api/requests/:id/edit` (requires latest revision `ready`) -> `comments` rows on current revision + `revisions(N+1, pending)` + `runs(edit, queued)` -> loop above, hydration also pulls prior revision's assets + open comments -> on success, those comments flip to `resolved`.

### Deploy
`POST /api/requests/:id/deploy` (requires latest revision `ready`) -> `runs(deploy, queued)`, no new revision -> loop above, agent drives a real browser against Adstream -> on success, `deploys` row written (`verified` only if both a real recording AND a detail-page read-back happened).

---

## 3. Concurrency

- Two independent pools: generate/edit share one cap (`GENERATION_CONCURRENCY_CAP`), deploy has its own (`DEPLOYMENT_CONCURRENCY_CAP`) - they never block each other.
- Enforced in Postgres (`claim_next_run` / `claim_next_deploy_run`), not in the dispatcher process - so it holds even across restarts or multiple dispatcher instances (though see failure scenarios below for what multiple instances with *different* caps does).
- Excess requests sit `queued`, picked up FIFO as slots free. No priority, no per-tenant fairness.

---

## 4. Failure scenarios - what actually happens in each

| Scenario | What happens | Self-heals? |
|---|---|---|
| Box killed, orchestrator still watching | `handle.wait()` raises, run marked `failed` with a real error, box destroyed | Yes - retry works cleanly |
| Orchestrator process dies, box keeps working | Agent finishes and uploads fine on its own; `runs` row stuck at `running` forever, nothing reads the result back | **No** - needs a human to read Storage and write the DB rows by hand |
| Box killed *before* the agent uploads anything for that attempt | Nothing from that attempt is recoverable - not in our DB, not in Storage, and (for deploy) not in Adstream either, since it has no backend of its own | No - by design, that attempt's work is genuinely gone; retry starts clean |
| Save (signed-URL upload) fails mid-run | Agent sees the failure as a tool result in its own conversation, in the same turn, and can retry/escalate itself | Yes, if the agent recovers; if not, `RESULT.json` records why |
| `running` row's box died and nobody's watching | `claim_next_run`/`claim_next_deploy_run` expire it after 20 minutes, mark `failed` | Yes, but *only* on elapsed time - it doesn't check whether the work actually succeeded, so a late-finishing success can get wrongly marked `failed` if a human doesn't catch it first |
| Retry after any failure | Always a full fresh attempt - never resumes mid-work, never reuses a partial save. For generation, a valid prior plate can still get silently overwritten by the retry's new one (no reuse, and it re-bills the image model) |
| Retry on a deploy specifically | **Not idempotent** - creates a second, duplicate ad, since each sandbox's browser session is independent and Adstream has no shared state to check against |
| Two dispatcher processes running with different caps | Each respects its *own* cap individually, but the true peak concurrency can reach the higher of the two - not a bug, a real operational fact | No - run exactly one dispatcher per environment |
| Cross-tenant/cross-job leak | Structurally can't happen - `hydrate_*()` takes explicit ids and refuses a mismatch; a sandbox's files are only ever the one tenant/job it was told about | N/A - prevented by construction, not detected after the fact |

---

## 5. Resume, isolation, day-two brands - one line each

- **Resume** = re-running the hydration recipe for the same `(tenant_id, request_id, revision_number)`. No snapshots, no diffs - `hydrate_*()` is a pure function, so replay is the whole mechanism.
- **Isolation** = a sandbox's filesystem never contains another tenant's data because hydration was never given that tenant's id - there's no "don't peek" rule to enforce.
- **New brand, zero code changes** = `onboard_tenant()` is slug-driven and idempotent; nothing downstream branches on a tenant's name anywhere in the codebase.
