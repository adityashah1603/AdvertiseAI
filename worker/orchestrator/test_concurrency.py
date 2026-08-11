"""
Phase 2: "the horrifying test case" (ROADMAP.md section 5), new-requests
half. Fires four requests across three tenants at once, in an order the
dispatcher - not this script - decides, through the real capped queue, and
PROVES (not just asserts) two things:

  1. the cap was actually respected (interval-overlap analysis on
     runs.started_at/ended_at, not just "it didn't crash")
  2. nothing crossed tenants or jobs (each output's overlay.html is
     downloaded from Storage and checked for its own headline copy and the
     ABSENCE of every other job's headline copy)

Before trusting (2), run test_leak_detection_canary.py once - it proves
the same check logic can actually catch a real (deliberately mislabeled)
leak, using already-completed Phase 1 outputs, at no extra spend.

Deliberately scoped to ONE canvas per run ("square") - canvas-size breadth
across all three tenants was already proven in Phase 1; multiplying that by
four concurrent runs would multiply real API spend for no additional
isolation evidence.

Deferred: the edit half of section 5's scenario ("Kahua edits theirs",
"Emplifi edits the first") - edit hydration doesn't exist yet (Phase 3
territory, pulled forward only as far as a backend-only edit path if/when
that's tackled next). See test_concurrency_edit.py, which covers this.

This spends real Anthropic + OpenAI money across up to CAP simultaneous
sandboxes - do not run without confirming first.
"""
import os
import re
import sys
import time

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(ROOT, ".env"))
sys.path.insert(0, os.path.join(ROOT, "supabase"))
sys.path.insert(0, os.path.join(ROOT, "worker", "hydration"))

from onboarding import get_client  # noqa: E402
from enqueue import enqueue_request  # noqa: E402
from dispatcher import run_dispatcher  # noqa: E402
from storage_paths import revision_prefix  # noqa: E402

CAP = 2
ONE_CANVAS = [{"name": "square", "width": 1080, "height": 1080}]

# Four requests, three tenants. Two are Emplifi with DIFFERENT copy - this
# proves job-level isolation within a single tenant too, not only
# cross-tenant isolation.
BATCH = [
    {
        "tenant_slug": "emplifi",
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
    {
        "tenant_slug": "emplifi",
        "campaign": "Creator Partnerships Q1",
        "copy": {
            "eyebrow": "Creator Partnerships",
            "headline": "Find creators your audience already trusts",
            "subhead": "Match briefs to vetted creators in one workspace, not six spreadsheets.",
            "cta": "See the workspace",
            "cta_href": "https://emplifi.example/creators",
            "legal": None,
        },
        "inspirations": [],
    },
    {
        "tenant_slug": "kahua",
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
    {
        "tenant_slug": "duolingo",
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
]


def _create_request(client, spec):
    tenant = client.table("tenants").select("id").eq("slug", spec["tenant_slug"]).single().execute().data
    tenant_id = tenant["id"]

    request = client.table("requests").insert({
        "tenant_id": tenant_id,
        "kind": "new",
        "campaign": spec["campaign"],
        "copy": spec["copy"],
        "canvases": ONE_CANVAS,
        "inspirations": spec["inspirations"],
        "created_by": "concurrency-test",
    }).execute().data[0]

    revision = client.table("revisions").insert({
        "request_id": request["id"],
        "revision_number": 1,
        "status": "pending",
    }).execute().data[0]

    return tenant_id, request["id"], revision["revision_number"]


def _visible_text(html):
    """Strip tags before comparing copy - a naive substring check on raw
    HTML breaks the moment an agent inserts a <br/> or <span> mid-headline
    for line-wrapping (a real, legitimate layout choice, not a leak).
    FINDING (2026-08-11): the first real run of this test flagged Duolingo
    as 'missing its own headline' purely because the agent wrote
    'Turn your coffee<br/>break into a streak' - correct content, just
    reformatted. Fixed by comparing visible text, not markup."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _max_overlap(intervals):
    """Max number of [start, end] intervals overlapping at any instant -
    proves the cap, rather than just trusting nothing crashed."""
    events = []
    for start, end in intervals:
        events.append((start, 1))
        events.append((end, -1))
    events.sort(key=lambda e: (e[0], e[1]))  # a run ending exactly when another starts doesn't count as overlap
    cur = peak = 0
    for _, delta in events:
        cur += delta
        peak = max(peak, cur)
    return peak


def main():
    client = get_client()

    tenant_count = len(set(s["tenant_slug"] for s in BATCH))
    print(f"Enqueueing {len(BATCH)} requests across {tenant_count} tenants...")
    jobs = []
    for spec in BATCH:
        tenant_id, request_id, revision_number = _create_request(client, spec)
        run_id = enqueue_request(tenant_id, request_id, revision_number, reason="concurrency-batch")
        jobs.append({
            "run_id": run_id, "tenant_id": tenant_id, "tenant_slug": spec["tenant_slug"],
            "request_id": request_id, "revision_number": revision_number, "campaign": spec["campaign"],
            "headline": spec["copy"]["headline"],
        })
        print(f"  queued run {run_id}  ({spec['tenant_slug']}: {spec['campaign']})")

    print(f"\nRunning dispatcher with cap={CAP} (drain mode - real spend starts now)...")
    t0 = time.time()
    run_dispatcher(CAP, drain=True)
    print(f"\nDispatcher drained in {time.time() - t0:.0f}s.")

    print("\n--- Verifying the cap was actually respected ---")
    run_ids = [j["run_id"] for j in jobs]
    rows = client.table("runs").select("*").in_("id", run_ids).execute().data
    intervals = [(r["started_at"], r["ended_at"]) for r in rows if r["started_at"] and r["ended_at"]]
    peak = _max_overlap(intervals)
    print(f"  peak concurrently-running count across the batch: {peak}  (cap was {CAP})")
    if peak > CAP:
        print(f"  CAP VIOLATED: {peak} runs overlapped, cap was {CAP}")
    else:
        print("  OK - cap respected.")

    print("\n--- Verifying no cross-tenant/cross-job content leakage ---")
    all_headlines = [j["headline"] for j in jobs]
    leaks = []
    for j in jobs:
        row = next(r for r in rows if r["id"] == j["run_id"])
        if row["status"] != "succeeded":
            print(f"  run {j['run_id']} ({j['tenant_slug']}) did not succeed "
                  f"(status={row['status']}) - skipping content check")
            continue
        tenant = client.table("tenants").select("*").eq("id", j["tenant_id"]).single().execute().data
        path = f"{revision_prefix(j['campaign'], j['request_id'], j['revision_number'])}/square/overlay.html"
        html = client.storage.from_(tenant["jobs_bucket"]).download(path).decode("utf-8", errors="replace")
        text = _visible_text(html)
        if j["headline"] not in text:
            leaks.append(f"run {j['run_id']} ({j['tenant_slug']}) is MISSING its own headline")
        for other in all_headlines:
            if other != j["headline"] and other in text:
                leaks.append(f"run {j['run_id']} ({j['tenant_slug']}) contains ANOTHER job's headline: {other!r}")

    if leaks:
        print("  LEAK CHECK FAILED:")
        for leak in leaks:
            print(f"    - {leak}")
    else:
        print("  OK - every output contains exactly its own headline, no one else's.")

    print("\n--- Summary ---")
    for j in jobs:
        row = next(r for r in rows if r["id"] == j["run_id"])
        print(f"  {j['tenant_slug']:10s} run={j['run_id']}  status={row['status']:10s} "
              f"started={row['started_at']}  ended={row['ended_at']}")

    return jobs, rows, peak, leaks


if __name__ == "__main__":
    main()
