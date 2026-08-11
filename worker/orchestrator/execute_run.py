"""
Phase 2: executes an already-claimed run.

This is deliberately everything run_generation.py used to do from step 2
(hydrate) onward, moved here so it can be called from many threads at once
by dispatcher.py - one thread per concurrently-running run. What used to be
one script doing "insert a queued run, then immediately run it" is now two
independent things: getting a run onto the queue (enqueue.py) and a worker
claiming + executing whatever the queue currently allows
(dispatcher.py -> claim_next_run() -> this file). This file assumes the run
is ALREADY 'running' with started_at already set - that happens inside
claim_next_run() (supabase/migrations/0002_concurrency_cap.sql), atomically
with the claim itself, so there is no gap where a run is claimed but not
yet marked running.
"""
import json
import os
import sys
import threading
from datetime import datetime, timezone

from dotenv import load_dotenv

# FINDING (2026-08-11): a real concurrency-test run was misreported as
# 'failed' - RESULT.json had actually landed fine in Storage - because a
# print() of the agent's own stdout (which can legitimately contain
# non-ASCII characters, e.g. an arrow in a summary) hit Windows' default
# console codepage and raised UnicodeEncodeError, which then got caught by
# this file's own except-and-mark-failed block. The bug was in *this
# script's logging*, not the pipeline. Reconfiguring stdout/stderr to UTF-8
# with errors="replace" up front means a log line can never itself crash
# the run it's trying to report on.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(ROOT, ".env"))

sys.path.insert(0, os.path.join(ROOT, "supabase"))
sys.path.insert(0, os.path.join(ROOT, "worker", "hydration"))
sys.path.insert(0, os.path.join(ROOT, "worker", "hydration", ".venv", "Lib", "site-packages"))

from onboarding import get_client  # noqa: E402
from generation import hydrate_generation  # noqa: E402
from storage_paths import revision_prefix  # noqa: E402
from upload_urls import mint_upload_urls  # noqa: E402

AGENT_DIR = os.path.join(ROOT, "worker", "sandbox_images", "generation")
SANDBOX_TIMEOUT_S = 900


def execute_claimed_run(run):
    client = get_client()
    run_id = run["id"]
    tenant_id = run["tenant_id"]
    request_id = run["request_id"]
    revision_number = run["revision_number"]
    reason = run.get("reason") or "initial"

    def log(msg):
        print(f"[run {run_id}] {msg}")

    # FINDING (2026-08-11): a run that died on the `e2b` import (module not
    # installed locally) was left stuck at status='running' forever -
    # claim_next_run() counts status='running' rows against the concurrency
    # cap, so an orphaned row like that silently eats capacity indefinitely.
    # Root cause: the only code that ever wrote 'failed' back to the runs
    # row was the except block below, but the try it belonged to used to
    # start well after this point - after the e2b import, the tenant/
    # request/revision fetch, and the revision->'generating' write. Any
    # exception in that unprotected prefix propagated straight past this
    # function, through dispatcher.py's own except (which only logs, on the
    # assumption this file "already recorded it to the run row"), and the
    # run row was never touched. revision_id is set only once the revision
    # fetch below actually succeeds, and the except block accounts for it
    # still being None.
    revision_id = None
    try:
        # Imported here, not at module load, so enqueue-only callers (and
        # the dispatcher's own claim loop) don't pay for/require the e2b
        # import - and inside this try, so a missing/broken import is
        # recorded as this run's failure instead of vanishing silently.
        # See sandbox_factory.py for why sandbox creation itself goes
        # through a shared helper rather than calling e2b directly here.
        from sandbox_factory import create_sandbox

        tenant = client.table("tenants").select("*").eq("id", tenant_id).single().execute().data
        request = client.table("requests").select("*").eq("id", request_id).single().execute().data
        prefix = revision_prefix(request["campaign"], request_id, revision_number)

        # The revisions row for (request_id, revision_number) always already
        # exists by the time a run executes - the request/edit-creation step
        # inserts it as 'pending' before any run is even enqueued (see
        # create_test_request.py / create_test_edit.py). This run's job is to
        # move that same row forward (generating -> ready/failed), never to
        # insert a second one - "a revision" is the request/number pair, not
        # any one run's attempt at it.
        revision = (
            client.table("revisions")
            .select("id")
            .eq("request_id", request_id)
            .eq("revision_number", revision_number)
            .single()
            .execute()
            .data
        )
        revision_id = revision["id"]
        client.table("revisions").update({"status": "generating"}).eq("id", revision_id).execute()

        # Written directly (this code already holds the service-role key for
        # DB access, unlike the sandbox), not via a signed URL - purely an
        # audit trail of WHY this attempt exists, alongside the canonical
        # plate/overlay/render/RESULT.json this run is about to produce.
        # Best-effort: a logging write failing should never fail the real run.
        # Nested try/except (rather than sharing the outer one) so a failure
        # here is swallowed as non-fatal instead of aborting the whole run -
        # that scoping is exactly why this can't be the outer try itself.
        try:
            started_at = run.get("started_at") or datetime.now(timezone.utc).isoformat()
            attempt_ts = started_at.replace(":", "-").split(".")[0]
            run_short = run_id.split("-")[0]
            attempt_path = f"{prefix}/attempts/{attempt_ts}-{run_short}-{reason}.json"
            client.storage.from_(tenant["jobs_bucket"]).upload(
                attempt_path,
                json.dumps({
                    "run_id": run_id, "type": run.get("type"), "reason": reason,
                    "started_at": started_at,
                }, indent=2).encode("utf-8"),
                {"upsert": "true"},
            )
            log(f"attempt logged: {attempt_path}")
        except Exception as e:  # noqa: BLE001 - audit trail, never worth failing the run over
            log(f"attempt log write failed (non-fatal): {e}")

        log("hydrating (skill + this tenant's real brand kit + this job's copy)...")
        files = hydrate_generation(tenant_id, request_id, revision_number)
        log(f"{len(files)} files")

        log("minting signed upload URLs, one per expected output file...")
        upload_urls = mint_upload_urls(tenant_id, request_id, revision_number)
        files["job/upload_urls.json"] = json.dumps(upload_urls).encode("utf-8")

        log("creating an anonymous E2B sandbox from the cq-generation-v1 template...")
        sbx = create_sandbox(template="cq-generation-v1", timeout=SANDBOX_TIMEOUT_S)
        log(f"sandbox_id: {sbx.sandbox_id}")
        client.table("runs").update({"sandbox_id": sbx.sandbox_id}).eq("id", run_id).execute()

        try:
            log("writing hydrated files + agent_runner.py into the sandbox...")
            all_files = dict(files)
            with open(os.path.join(AGENT_DIR, "agent_runner.py"), "rb") as f:
                all_files["agent_runner.py"] = f.read()
            for rel_path, data in all_files.items():
                # FINDING (2026-08-11): the transient TLS/connection-reset
                # errors first seen in finding #11 recurred often enough in
                # this session (3 of 4 back-to-back attempts, on a different
                # file each time) that hand-retrying the whole run every
                # time stopped being reasonable. A different file failing
                # each time rules out a bad file and points at the
                # connection itself - a bounded retry on just the one write
                # that failed is the correct fix, not a bigger hammer.
                for attempt in range(3):
                    try:
                        sbx.files.write(rel_path, data, request_timeout=30)
                        break
                    except Exception as e:  # noqa: BLE001 - narrowed by re-raising on the last attempt
                        if attempt == 2:
                            raise
                        log(f"  write of {rel_path} failed (attempt {attempt + 1}/3): {e} - retrying...")
            log(f"wrote {len(all_files)} files total")

            log("executing agent_runner.py INSIDE the sandbox "
                "(real Anthropic + OpenAI spend starts now)...")
            anthropic_key = os.environ["ANTHROPIC_API_KEY"]
            openai_key = os.environ["OPENAI_API_KEY"]

            handle = sbx.commands.run(
                "python agent_runner.py .",
                background=True,
                envs={
                    "ANTHROPIC_API_KEY": anthropic_key,
                    "OPENAI_API_KEY": openai_key,
                    "PLAYWRIGHT_BROWSERS_PATH": "/ms-playwright",
                },
                timeout=SANDBOX_TIMEOUT_S - 60,
            )

            wait_outcome = {}

            def _wait_for_agent():
                try:
                    wait_outcome["result"] = handle.wait(
                        on_stdout=lambda s: log(f"[sandbox] {s.rstrip()}"),
                        on_stderr=lambda s: log(f"[sandbox:err] {s.rstrip()}"),
                    )
                except Exception as e:  # noqa: BLE001 - re-surfaced below
                    wait_outcome["error"] = e

            wait_thread = threading.Thread(target=_wait_for_agent, daemon=True)
            wait_thread.start()

            while wait_thread.is_alive():
                wait_thread.join(timeout=15)
                if wait_thread.is_alive():
                    try:
                        metrics = sbx.get_metrics()
                        if metrics:
                            m = metrics[-1]
                            mem_pct = (m.mem_used / m.mem_total * 100) if m.mem_total else 0
                            log(f"[metrics] cpu={m.cpu_used_pct:.0f}%  "
                                f"mem={m.mem_used / 1e6:.0f}MB/{m.mem_total / 1e6:.0f}MB ({mem_pct:.0f}%)")
                    except Exception as e:
                        log(f"[metrics] fetch failed: {e}")

            if "error" in wait_outcome:
                err = wait_outcome["error"]
                if hasattr(err, "exit_code"):
                    agent_result = err
                    log(f"agent process exited non-zero (exit code {agent_result.exit_code})")
                else:
                    raise err
            else:
                agent_result = wait_outcome["result"]
                log(f"agent process exit code: {agent_result.exit_code}")

        finally:
            log(f"destroying sandbox {sbx.sandbox_id}...")
            sbx.kill()
            log("destroyed")

        log("verifying success by reading Storage back - NOT the (now-destroyed) sandbox...")
        result_path = f"{prefix}/RESULT.json"
        try:
            result_bytes = client.storage.from_(tenant["jobs_bucket"]).download(result_path)
            log(f"RESULT.json found in Storage ({len(result_bytes)} bytes) - run produced real output")
            status = "succeeded" if agent_result.exit_code == 0 else "failed"
        except Exception as e:
            log(f"RESULT.json NOT found in Storage: {e}")
            status = "failed"

        ended_at = datetime.now(timezone.utc).isoformat()
        run_update = {"status": status, "ended_at": ended_at}
        if status == "succeeded":
            # Both sides of the mutual FK get linked only now, on the run
            # that actually produced a real, storage-verified result -
            # never speculatively at start, matching runs.revision_id
            # being "nullable until it produces one".
            run_update["revision_id"] = revision_id
            client.table("revisions").update(
                {"status": "ready", "run_id": run_id}
            ).eq("id", revision_id).execute()

            # Index into the durable artifacts this run just produced - the
            # assets table exists precisely so a caller (the frontend) can
            # ask "what images exist for this revision" from Postgres
            # without recomputing Storage paths itself. upsert on the
            # existing (revision_id, canvas_name) unique constraint so a
            # retry overwrites cleanly instead of erroring or duplicating.
            for canvas in request["canvases"]:
                name = canvas["name"]
                client.table("assets").upsert({
                    "revision_id": revision_id,
                    "canvas_name": name,
                    "width": canvas["width"],
                    "height": canvas["height"],
                    "plate_path": f"{prefix}/{name}/plate.png",
                    "html_path": f"{prefix}/{name}/overlay.html",
                    "png_path": f"{prefix}/{name}/render.png",
                }, on_conflict="revision_id,canvas_name").execute()
            log(f"recorded {len(request['canvases'])} asset row(s)")

            # DECISIONS.md SS3.2: "resolved - an edit run that named this
            # comment in its prompt completed and produced the next
            # revision." _hydrate_edit_context() (generation.py) always pulls
            # EVERY open comment on the prior revision into the prompt, never
            # a filtered subset - so "named in the prompt" is exactly "was
            # open on the revision this run just produced the successor of."
            # No agent-side reporting of which comments it addressed is
            # needed; resolution is a pure function of which run succeeded
            # against which prior revision.
            if revision_number > 1:
                prior_revision = (
                    client.table("revisions")
                    .select("id")
                    .eq("request_id", request_id)
                    .eq("revision_number", revision_number - 1)
                    .single()
                    .execute()
                    .data
                )
                resolved = (
                    client.table("comments")
                    .update({"status": "resolved"})
                    .eq("revision_id", prior_revision["id"])
                    .eq("status", "open")
                    .execute()
                )
                log(f"resolved {len(resolved.data)} comment(s) on prior revision {revision_number - 1}")
        else:
            client.table("revisions").update({"status": "failed"}).eq("id", revision_id).execute()
        client.table("runs").update(run_update).eq("id", run_id).execute()
        log(f"marked '{status}'.")
        return run_id, status

    except Exception as e:
        ended_at = datetime.now(timezone.utc).isoformat()
        client.table("runs").update({
            "status": "failed", "error_message": str(e)[:2000], "ended_at": ended_at,
        }).eq("id", run_id).execute()
        # revision_id is only set once the revision fetch above succeeds -
        # an earlier failure (e2b import, tenant/request/revision fetch)
        # has no revision row to mark, only the run row.
        if revision_id:
            client.table("revisions").update({"status": "failed"}).eq("id", revision_id).execute()
        log(f"FAILED: {e}")
        raise


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python execute_run.py <run_id>  (run must already be 'running')")
        sys.exit(1)
    client = get_client()
    run = client.table("runs").select("*").eq("id", sys.argv[1]).single().execute().data
    execute_claimed_run(run)
