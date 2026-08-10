"""
Dev-only helper: creates ONE request + its first revision row, so
hydrate_generation() has something real to read before a frontend exists to
create requests properly. Not production code - Step 4's real request-intake
flow (and, later, the feedback surface for edits) replaces this entirely.

Reuses Emplifi's real "2026 Predictions" campaign copy from
starter/starter/requests/new-request.example.json, for direct continuity
with what Phase 0 already proved works by hand.

Usage:
    python create_test_request.py
"""
import os
import sys

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(ROOT, ".env"))
sys.path.insert(0, os.path.join(ROOT, "supabase"))

from onboarding import get_client  # noqa: E402


def main():
    client = get_client()

    tenant = client.table("tenants").select("id").eq("slug", "emplifi").single().execute().data
    tenant_id = tenant["id"]

    request = client.table("requests").insert({
        "tenant_id": tenant_id,
        "kind": "new",
        "campaign": "2026 Social Commerce Predictions",
        "copy": {
            "eyebrow": "2026 Predictions",
            "headline": "Shoppable video becomes the default discovery surface",
            "subhead": "TikTok Shop now hosts 500,000+ US sellers. Your feed is a storefront.",
            "cta": "Get the predictions",
            "cta_href": "https://emplifi.example/predictions-2026",
            "legal": None,
        },
        "canvases": [
            {"name": "square", "width": 1080, "height": 1080},
            {"name": "landscape", "width": 1200, "height": 628},
            {"name": "portrait", "width": 1080, "height": 1350},
        ],
        # Leaderboard (728x90) deliberately excluded - still blocked per
        # phase0/README.md finding #2/#2b, unresolved with the CEO.
        "inspirations": ["emplifi-predictions-square.png"],
        "created_by": "dev-test",
    }).execute().data[0]

    revision = client.table("revisions").insert({
        "request_id": request["id"],
        "revision_number": 1,
        "status": "pending",
    }).execute().data[0]

    print(f"tenant_id:        {tenant_id}")
    print(f"request_id:       {request['id']}")
    print(f"revision_number:  {revision['revision_number']}")
    print()
    print("Test hydration with:")
    print(f"  python generation.py {tenant_id} {request['id']} 1")


if __name__ == "__main__":
    main()
