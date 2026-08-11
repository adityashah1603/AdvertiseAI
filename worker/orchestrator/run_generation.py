"""
Manual/debug single-run entrypoint - deliberately NOT concurrency-cap-aware.
Enqueues a run and executes it immediately in this process, bypassing
claim_next_run() entirely. This is what every Phase 0/1 run used, and stays
useful for "just run this one thing and watch it" testing.

For the real capped-FIFO path multiple concurrent runs must go through -
where a run may sit in 'queued' for a while and get claimed later by a
dispatcher, possibly out of submission order - see dispatcher.py and
supabase/migrations/0002_concurrency_cap.sql. Both paths call the same
execute_claimed_run() (execute_run.py), so there is exactly one
implementation of "what a run actually does."
"""
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(ROOT, ".env"))
sys.path.insert(0, os.path.join(ROOT, "supabase"))

from onboarding import get_client  # noqa: E402
from execute_run import execute_claimed_run  # noqa: E402


def run_generation(tenant_id, request_id, revision_number):
    client = get_client()

    print("1. Recording the run's existence before anything else happens...")
    started_at = datetime.now(timezone.utc).isoformat()
    run = client.table("runs").insert({
        "type": "generate",
        "tenant_id": tenant_id,
        "request_id": request_id,
        "revision_number": revision_number,
        "status": "running",
        "started_at": started_at,
        "reason": "manual",
    }).execute().data[0]
    print(f"   run_id: {run['id']}")

    print("\n2-8. Hydrating, sandboxing, running the agent, verifying, updating status...")
    return execute_claimed_run(run)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python run_generation.py <tenant_id> <request_id> <revision_number>")
        sys.exit(1)
    run_generation(sys.argv[1], sys.argv[2], int(sys.argv[3]))
