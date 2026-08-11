"""
Phase 2: the dispatcher. Replaces "run_generation.py does one run,
synchronously, start to finish" with a real capped-FIFO worker pool that
enforces ROADMAP.md section 5's concurrency cap.

The cap is NOT enforced by anything in this process's memory (no local
semaphore, no in-process counter) - it's enforced by claim_next_run()
(supabase/migrations/0002_concurrency_cap.sql), a Postgres function that
atomically checks runs.status='running' count against the cap and claims
the oldest queued run only if there's room. That's deliberate: it means
running two dispatcher processes at once (or restarting this one mid-run)
still respects the same cap globally, because the cap lives in Postgres,
not in this script.

This script's own ThreadPoolExecutor is just a convenience for running
multiple claimed executions concurrently within one process - it is sized
to the combined cap so it never even attempts more than the DB would
allow, but the DB check is what actually matters.

Phase 4 addition: deploy runs ('type'='deploy') are claimed and counted
completely separately from generate/edit runs, via claim_next_deploy_run()
(supabase/migrations/0009_deploy_concurrency_cap.sql) and its own
GENERATION_CONCURRENCY_CAP-independent env var, DEPLOYMENT_CONCURRENCY_CAP -
"two independent caps, not one... should never block each other"
(DECISIONS.md SS3.3). Polled in the same loop, routed to a different
executor by run type, but never sharing a slot count with generation/edit.
"""
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(ROOT, ".env"))
sys.path.insert(0, os.path.join(ROOT, "supabase"))

from onboarding import get_client  # noqa: E402
from execute_run import execute_claimed_run  # noqa: E402
from execute_deploy_run import execute_claimed_deploy_run  # noqa: E402

POLL_INTERVAL_S = 3


def run_dispatcher(cap, drain=True, deploy_cap=None):
    """
    drain=True (used by the concurrency test): stop once neither
    claim_next_run() nor claim_next_deploy_run() has anything more to give
    AND no run is still queued/running - i.e. all enqueued work has
    finished. drain=False: poll forever, like a real always-on worker
    process would.

    deploy_cap defaults to DEPLOYMENT_CONCURRENCY_CAP - kept as a separate
    parameter (not derived from `cap`) so the two pools are visibly
    independent at every call site, not just in the SQL.
    """
    if deploy_cap is None:
        deploy_cap = int(os.environ.get("DEPLOYMENT_CONCURRENCY_CAP", 1))

    client = get_client()
    futures = []

    with ThreadPoolExecutor(max_workers=cap + deploy_cap) as pool:
        while True:
            got_work = False

            claimed = client.rpc("claim_next_run", {"p_cap": cap}).execute().data
            if claimed:
                run = claimed[0]
                print(f"[dispatcher] claimed run {run['id']} "
                      f"(tenant={run['tenant_id']}, request={run['request_id']}, "
                      f"revision={run['revision_number']})")
                futures.append(pool.submit(_run_and_report, run))
                got_work = True

            claimed_deploy = client.rpc("claim_next_deploy_run", {"p_cap": deploy_cap}).execute().data
            if claimed_deploy:
                run = claimed_deploy[0]
                print(f"[dispatcher] claimed DEPLOY run {run['id']} "
                      f"(tenant={run['tenant_id']}, request={run['request_id']}, "
                      f"revision={run['revision_number']})")
                futures.append(pool.submit(_run_and_report_deploy, run))
                got_work = True

            if got_work:
                continue  # try to claim more immediately, no need to sleep

            if drain:
                remaining = client.table("runs").select("id").in_(
                    "status", ["queued", "running"]
                ).execute()
                if not remaining.data:
                    break

            time.sleep(POLL_INTERVAL_S)

        for f in futures:
            f.result()  # re-raise any worker exception in the main thread

    print("[dispatcher] drained - no queued or running work left.")


def _run_and_report(run):
    try:
        return execute_claimed_run(run)
    except Exception as e:  # noqa: BLE001 - already recorded to the run row; log and move on
        print(f"[dispatcher] run {run['id']} raised: {e}")
        return run["id"], "failed"


def _run_and_report_deploy(run):
    try:
        return execute_claimed_deploy_run(run)
    except Exception as e:  # noqa: BLE001 - already recorded to the run row; log and move on
        print(f"[dispatcher] deploy run {run['id']} raised: {e}")
        return run["id"], "failed"


if __name__ == "__main__":
    # --serve: run forever, polling for new work as it's submitted (what a
    # live frontend needs behind it) instead of draining once and exiting
    # (what the one-off manual/test invocations of this script have always
    # wanted). Same run_dispatcher() either way - only whether it stops once
    # the queue empties differs.
    args = [a for a in sys.argv[1:] if a != "--serve"]
    serve = "--serve" in sys.argv
    if len(args) > 1:
        print("Usage: python dispatcher.py [concurrency_cap] [--serve]")
        sys.exit(1)
    cap = int(args[0]) if args else int(os.environ.get("GENERATION_CONCURRENCY_CAP", 2))
    run_dispatcher(cap, drain=not serve)
