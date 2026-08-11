"""
Dev-only helper: the edit-flow equivalent of create_test_request.py. Given
a request that already has a succeeded revision, inserts one or more
`open` comments against that revision and creates the next revisions row -
exactly the DB state a real "leave feedback, ask for a new revision" UI
action would produce, minus the UI itself (Phase 3 territory).

Usage:
    python create_test_edit.py <request_id>
"""
import os
import sys

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(ROOT, ".env"))
sys.path.insert(0, os.path.join(ROOT, "supabase"))

from onboarding import get_client  # noqa: E402

# Two comments deliberately of different kinds - one a pure overlay tweak
# (CTA is styled wrong), one that's arguably about composition (headline
# placement) but still resolvable without touching the plate. Neither
# comment says "regenerate the photo" - a real full-replate comment is a
# separate, later test, not needed to prove the mechanism works.
DEFAULT_EDIT_COMMENTS = [
    {
        "canvas_name": "square",
        "region": {"x": 84, "y": 384, "width": 200, "height": 56},
        "body": "The CTA pill needs to be solid Kahua orange (#FF5A21), not an outline - "
                "right now it barely reads as a button.",
        "author": "concurrency-test-edit",
    },
    {
        "canvas_name": "square",
        "region": {"x": 60, "y": 100, "width": 900, "height": 200},
        "body": "Headline is sitting a little too close to the top edge - please add some breathing room above it.",
        "author": "concurrency-test-edit",
    },
]


def create_edit_request(client, request_id, comments):
    request = client.table("requests").select("*").eq("id", request_id).single().execute().data
    tenant_id = request["tenant_id"]

    revisions = (
        client.table("revisions")
        .select("*")
        .eq("request_id", request_id)
        .order("revision_number", desc=True)
        .execute()
        .data
    )
    if not revisions:
        raise ValueError(f"request {request_id} has no revisions to edit.")
    latest = revisions[0]

    succeeded_run = (
        client.table("runs")
        .select("id")
        .eq("request_id", request_id)
        .eq("revision_number", latest["revision_number"])
        .eq("status", "succeeded")
        .limit(1)
        .execute()
        .data
    )
    if not succeeded_run:
        raise ValueError(
            f"request {request_id}'s latest revision ({latest['revision_number']}) "
            f"has no succeeded run - nothing real to edit yet."
        )

    for c in comments:
        client.table("comments").insert({
            "request_id": request_id,
            "revision_id": latest["id"],
            "canvas_name": c["canvas_name"],
            "region": c["region"],
            "body": c["body"],
            "author": c.get("author"),
            "status": "open",
        }).execute()

    new_revision_number = latest["revision_number"] + 1
    client.table("revisions").insert({
        "request_id": request_id,
        "revision_number": new_revision_number,
        "status": "pending",
    }).execute()

    return tenant_id, request_id, new_revision_number


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python create_test_edit.py <request_id>")
        sys.exit(1)

    client = get_client()
    tenant_id, request_id, revision_number = create_edit_request(client, sys.argv[1], DEFAULT_EDIT_COMMENTS)

    print(f"tenant_id:        {tenant_id}")
    print(f"request_id:       {request_id}")
    print(f"revision_number:  {revision_number}  (edit)")
    print()
    print("Enqueue it with:")
    print(f"  from enqueue import enqueue_request")
    print(f"  enqueue_request('{tenant_id}', '{request_id}', {revision_number}, run_type='edit')")
