"""
Phase 2: enqueue only. Inserts a runs row with status='queued' and returns
its id - claiming and executing it is the dispatcher's job (dispatcher.py
+ execute_run.py), not this function's.

Split out of what used to be run_generation.py's first step so many
requests can be put on the queue up front, independently of when, in what
order, or by which worker they actually execute - which is the entire
point of proving the concurrency cap in ROADMAP.md section 5.
"""
import os
import sys

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(ROOT, ".env"))
sys.path.insert(0, os.path.join(ROOT, "supabase"))

from onboarding import get_client  # noqa: E402


def enqueue_request(tenant_id, request_id, revision_number, run_type="generate", reason="initial"):
    """reason is free text describing WHY this attempt exists - 'initial',
    'retry-after-<short_run_id>:<error class>', 'concurrency-batch', etc.
    Carried onto the run row and, once execution starts, into a small
    per-attempt log file in Storage (see execute_run.py) - so a retry's
    justification is visible without cross-referencing this table."""
    client = get_client()
    run = client.table("runs").insert({
        "type": run_type,
        "tenant_id": tenant_id,
        "request_id": request_id,
        "revision_number": revision_number,
        "status": "queued",
        "reason": reason,
    }).execute().data[0]
    return run["id"]


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python enqueue.py <tenant_id> <request_id> <revision_number>")
        sys.exit(1)
    run_id = enqueue_request(sys.argv[1], sys.argv[2], int(sys.argv[3]))
    print(f"run_id: {run_id} (status=queued)")
