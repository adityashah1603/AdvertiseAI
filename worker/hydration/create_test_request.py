"""
Dev-only helper: creates ONE request + its first revision row, so
hydrate_generation() / run_generation.py have something real to work
against before a frontend exists to create requests properly. Not
production code - Step 4's real request-intake flow (and, later, the
feedback surface for edits) replaces this entirely.

Refactored to be tenant-parameterized rather than Emplifi-only - the whole
point of Phase 1 is proving the pipeline isn't brand-specific, so the test
data it runs against shouldn't be hardcoded to one brand either. One
function, reused for every brand, not a copy-pasted script per tenant.

Usage:
    python create_test_request.py emplifi
    python create_test_request.py kahua
"""
import os
import sys

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(ROOT, ".env"))
sys.path.insert(0, os.path.join(ROOT, "supabase"))

from onboarding import get_client  # noqa: E402

# Same campaign copy already validated by hand in Phase 0 for each brand -
# reusing it here means the sandboxed run is directly comparable to the
# already-reviewed Phase 0 renders, not a fresh unvalidated request.
TEST_REQUESTS = {
    "emplifi": {
        "campaign": "2026 Social Commerce Predictions",
        "copy": {
            "eyebrow": "2026 Predictions",
            "headline": "Shoppable video becomes the default discovery surface",
            "subhead": "TikTok Shop now hosts 500,000+ US sellers. Your feed is a storefront.",
            "cta": "Get the predictions",
            "cta_href": "https://emplifi.example/predictions-2026",
            "legal": None,
        },
        "inspirations": ["emplifi-predictions-square.png"],
    },
    "kahua": {
        "campaign": "Field to Office",
        "copy": {
            "eyebrow": "Field to Office",
            "headline": "Track every RFI before it becomes a change order",
            "subhead": "Kahua keeps RFIs, submittals and change orders on one timeline your whole team can see.",
            "cta": "See how it works",
            "cta_href": "https://kahua.example/field-to-office",
            "legal": None,
        },
        "inspirations": [],
    },
    "duolingo": {
        # The generalization-test brand: no real logo (unlicensable
        # trademark, omitted on purpose - see third-brand-test/duolingo/),
        # provisional/inferred type-scale numbers. The real closing test of
        # "zero code changes for a brand-agnostic pipeline."
        "campaign": "5 Minutes a Day",
        "copy": {
            "eyebrow": "5 Minutes a Day",
            "headline": "Turn your coffee break into a streak",
            "subhead": "Bite-sized lessons, real progress. Showing up is the whole game.",
            "cta": "Start your streak",
            "cta_href": "https://duolingo.example/start",
            "legal": None,
        },
        "inspirations": [],
    },
}

# Leaderboard (728x90) deliberately dropped from scope entirely (decision,
# 2026-08-11, see phase1.md section 3): the real goal is Facebook/Instagram/
# TikTok compatibility, and a 728x90 IAB banner isn't a native placement on
# any of those three anyway - not worth the architectural fight it would
# take (gpt-image-2's 3:1 max ratio + total-pixel floor make it impossible
# outright, not just inconvenient).
#
# "story" (1080x1920, 9:16) added in its place - the actual native shape for
# Instagram/Facebook Stories, Reels, and TikTok's primary format. Unlike the
# leaderboard, this ratio is well within gpt-image-2's real constraints (9:16
# = 0.5625, nowhere near the 3:1 cap; 1080x1920 = 2,073,600px, comfortably
# inside the 655,360-8,294,400 floor/ceiling) - the existing divisible-by-16
# rounding in call_gpt_image.py handles the rest, same as every other size.
CANVASES = [
    {"name": "square", "width": 1080, "height": 1080},
    {"name": "landscape", "width": 1200, "height": 628},
    {"name": "portrait", "width": 1080, "height": 1350},
    {"name": "story", "width": 1080, "height": 1920},
]


def create_test_request(client, tenant_slug: str):
    if tenant_slug not in TEST_REQUESTS:
        raise ValueError(f"No test request defined for '{tenant_slug}'. Known: {list(TEST_REQUESTS)}")

    tenant = client.table("tenants").select("id").eq("slug", tenant_slug).single().execute().data
    tenant_id = tenant["id"]
    spec = TEST_REQUESTS[tenant_slug]

    request = client.table("requests").insert({
        "tenant_id": tenant_id,
        "kind": "new",
        "campaign": spec["campaign"],
        "copy": spec["copy"],
        "canvases": CANVASES,
        "inspirations": spec["inspirations"],
        "created_by": "dev-test",
    }).execute().data[0]

    revision = client.table("revisions").insert({
        "request_id": request["id"],
        "revision_number": 1,
        "status": "pending",
    }).execute().data[0]

    return tenant_id, request["id"], revision["revision_number"]


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in TEST_REQUESTS:
        print(f"Usage: python create_test_request.py <{'|'.join(TEST_REQUESTS)}>")
        sys.exit(1)

    client = get_client()
    tenant_id, request_id, revision_number = create_test_request(client, sys.argv[1])

    print(f"tenant_id:        {tenant_id}")
    print(f"request_id:       {request_id}")
    print(f"revision_number:  {revision_number}")
    print()
    print("Run the real sandboxed pipeline with:")
    print(f"  cd ../orchestrator && ./.venv/Scripts/python.exe run_generation.py {tenant_id} {request_id} {revision_number}")


if __name__ == "__main__":
    main()
