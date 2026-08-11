"""
Manual/debug single-deploy-run entrypoint - the deploy-side equivalent of
run_generation.py. Enqueues a deploy run and executes it immediately in this
process, bypassing claim_next_run() entirely. Exists specifically so the
FIRST real deploy-agent runs can be watched and iterated on without ever
touching the live dispatcher.py --serve process the working demo depends on.

Once execute_deploy_run.py has a clean, verified pass, dispatcher.py gets a
small routing addition and this manual path stops being the only way in -
but this file stays useful for the same one-off "just run this and watch"
testing run_generation.py already serves for generation.

Usage:
    python run_deploy.py <tenant_id> <request_id> <revision_number>
"""
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(ROOT, ".env"))
sys.path.insert(0, os.path.join(ROOT, "supabase"))

from onboarding import get_client  # noqa: E402
from execute_deploy_run import execute_claimed_deploy_run  # noqa: E402


def run_deploy(tenant_id, request_id, revision_number):
    client = get_client()

    print("1. Recording the deploy run's existence before anything else happens...")
    started_at = datetime.now(timezone.utc).isoformat()
    run = client.table("runs").insert({
        "type": "deploy",
        "tenant_id": tenant_id,
        "request_id": request_id,
        "revision_number": revision_number,
        "status": "running",
        "started_at": started_at,
        "reason": "manual",
    }).execute().data[0]
    print(f"   run_id: {run['id']}")

    print("\n2-8. Hydrating, sandboxing, driving Adstream, verifying, updating status...")
    return execute_claimed_deploy_run(run)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python run_deploy.py <tenant_id> <request_id> <revision_number>")
        sys.exit(1)
    run_deploy(sys.argv[1], sys.argv[2], int(sys.argv[3]))
