"""
Phase 3 backlog item: the other half of "the horrifying test case"
(ROADMAP.md section 5) that test_concurrency.py never covered - concurrent
EDITS across tenants ("Kahua edits it... Emplifi edits the first..."), not
just concurrent new tasks.

Deliberately reuses already-succeeded revisions already sitting in the
database (real prior generation/edit runs) rather than paying for fresh
plates first - the point of this test is proving the EDIT path's hydration
correctness under concurrency (right tenant, right task, right prior
revision, right comment), which doesn't require a fresh plate to exercise.
For each onboarded tenant, the newest request whose latest revision is
'ready' is used as-is; a tenant with no such request is skipped with a
clear message rather than failing the whole run over one tenant's missing
fixture data.

Same two proofs as test_concurrency.py, applied to the post-edit outputs:
  1. the cap was actually respected (interval-overlap analysis on
     runs.started_at/ended_at)
  2. nothing crossed tenants - each tenant's edit comment instructs a
     literal, otherwise-never-occurring marker string into its CTA label;
     each job's resulting overlay.html is checked for its own marker AND
     the absence of every other job's marker. This is a stronger, edit-
     specific leak signal than test_concurrency.py's own-headline check
     (which a byte-identical-plate edit wouldn't even touch), and it
     transitively proves the edit hydrated its OWN tenant's correct prior
     revision + comment, never another tenant's.

This spends real Anthropic + OpenAI money across up to CAP simultaneous
sandboxes - do not run without confirming first.
"""
import os
import re
import sys
import time
import uuid

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(ROOT, ".env"))
sys.path.insert(0, os.path.join(ROOT, "supabase"))
sys.path.insert(0, os.path.join(ROOT, "worker", "hydration"))

from onboarding import get_client  # noqa: E402
from enqueue import enqueue_request  # noqa: E402
from dispatcher import run_dispatcher  # noqa: E402
from storage_paths import revision_prefix  # noqa: E402


def _visible_text(html):
    """Same tag-stripping test_concurrency.py's own leak check uses - a
    naive substring check on raw HTML breaks the moment the agent wraps a
    marker across a <span> for layout, which is a legitimate choice, not a
    leak."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _max_overlap(intervals):
    events = []
    for start, end in intervals:
        events.append((start, 1))
        events.append((end, -1))
    events.sort(key=lambda e: (e[0], e[1]))
    cur = peak = 0
    for _, delta in events:
        cur += delta
        peak = max(peak, cur)
    return peak


def _find_editable_request(client, tenant_id):
    """The newest request for this tenant whose LATEST revision is 'ready' -
    exactly the precondition the real /edit route and
    _hydrate_edit_context() both require. Returns None if this tenant has
    nothing eligible."""
    requests = (
        client.table("requests")
        .select("id,campaign,canvases")
        .eq("tenant_id", tenant_id)
        .order("created_at", desc=True)
        .execute()
        .data
    )
    for request in requests:
        revisions = (
            client.table("revisions")
            .select("id,revision_number,status")
            .eq("request_id", request["id"])
            .order("revision_number", desc=True)
            .limit(1)
            .execute()
            .data
        )
        if revisions and revisions[0]["status"] == "ready":
            return request, revisions[0]
    return None


def main():
    client = get_client()

    tenants = client.table("tenants").select("*").execute().data
    print(f"Checking {len(tenants)} tenant(s) for an editable (latest-revision-ready) request...")

    jobs = []
    for tenant in tenants:
        found = _find_editable_request(client, tenant["id"])
        if not found:
            print(f"  SKIP {tenant['slug']}: no request with a 'ready' latest revision")
            continue
        request, latest_revision = found
        marker = f"AUDIT-{tenant['slug'].upper()}-{uuid.uuid4().hex[:8]}"
        canvas = request["canvases"][0]
        jobs.append({
            "tenant_id": tenant["id"],
            "tenant_slug": tenant["slug"],
            "request_id": request["id"],
            "campaign": request["campaign"],
            "canvas_name": canvas["name"],
            "canvas_w": canvas["width"],
            "canvas_h": canvas["height"],
            "prior_revision_number": latest_revision["revision_number"],
            "next_revision_number": latest_revision["revision_number"] + 1,
            "marker": marker,
        })
        print(f"  OK   {tenant['slug']}: request={request['id']} "
              f"(editing revision {latest_revision['revision_number']} -> "
              f"{latest_revision['revision_number'] + 1})")

    if len(jobs) < 2:
        print(f"\nOnly {len(jobs)} tenant(s) eligible - need at least 2 for a real "
              "cross-tenant concurrency proof. Run generations for more tenants first.")
        return jobs, [], 0, ["not enough eligible tenants to prove cross-tenant isolation"]

    cap = min(len(jobs), 2)
    print(f"\nInserting one marker comment + enqueueing one edit run per eligible tenant "
          f"(cap={cap})...")
    for j in jobs:
        client.table("comments").insert({
            "request_id": j["request_id"],
            "revision_id": client.table("revisions").select("id")
                .eq("request_id", j["request_id"])
                .eq("revision_number", j["prior_revision_number"])
                .single().execute().data["id"],
            "canvas_name": j["canvas_name"],
            "region": {"x": 0, "y": 0, "width": j["canvas_w"], "height": j["canvas_h"]},
            "body": f"Change the CTA button label text to read exactly '{j['marker']}' "
                    f"(replace whatever it currently says with this, do not change anything else).",
            "author": "concurrency-edit-test",
        }).execute()
        client.table("revisions").insert({
            "request_id": j["request_id"],
            "revision_number": j["next_revision_number"],
            "status": "pending",
        }).execute()
        run_id = enqueue_request(
            j["tenant_id"], j["request_id"], j["next_revision_number"],
            run_type="edit", reason="concurrency-edit-batch",
        )
        j["run_id"] = run_id
        print(f"  queued edit run {run_id}  ({j['tenant_slug']}: {j['campaign']})")

    print(f"\nRunning dispatcher with cap={cap} (drain mode - real spend starts now)...")
    t0 = time.time()
    run_dispatcher(cap, drain=True)
    print(f"\nDispatcher drained in {time.time() - t0:.0f}s.")

    print("\n--- Verifying the cap was actually respected ---")
    run_ids = [j["run_id"] for j in jobs]
    rows = client.table("runs").select("*").in_("id", run_ids).execute().data
    intervals = [(r["started_at"], r["ended_at"]) for r in rows if r["started_at"] and r["ended_at"]]
    peak = _max_overlap(intervals)
    print(f"  peak concurrently-running count across the batch: {peak}  (cap was {cap})")
    if peak > cap:
        print(f"  CAP VIOLATED: {peak} runs overlapped, cap was {cap}")
    else:
        print("  OK - cap respected.")

    print("\n--- Verifying no cross-tenant marker leakage in the edited outputs ---")
    all_markers = [j["marker"] for j in jobs]
    leaks = []
    checked = 0
    for j in jobs:
        row = next(r for r in rows if r["id"] == j["run_id"])
        if row["status"] != "succeeded":
            print(f"  run {j['run_id']} ({j['tenant_slug']}) did not succeed "
                  f"(status={row['status']}) - skipping content check")
            continue
        tenant = client.table("tenants").select("*").eq("id", j["tenant_id"]).single().execute().data
        path = (f"{revision_prefix(j['campaign'], j['request_id'], j['next_revision_number'])}/"
                f"{j['canvas_name']}/overlay.html")
        html = client.storage.from_(tenant["jobs_bucket"]).download(path).decode("utf-8", errors="replace")
        text = _visible_text(html)
        checked += 1
        if j["marker"] not in text:
            leaks.append(f"run {j['run_id']} ({j['tenant_slug']}) is MISSING its own marker "
                         f"'{j['marker']}' - edit may not have applied, or hydrated the wrong comment")
        for other in all_markers:
            if other != j["marker"] and other in text:
                leaks.append(f"run {j['run_id']} ({j['tenant_slug']}) contains ANOTHER "
                             f"tenant's marker: {other!r}")

    # A clean-looking "no leaks" from zero actually-checked jobs proves
    # nothing - distinguish that explicitly rather than letting an empty
    # `leaks` list read the same as a real pass (this test script's own bug,
    # caught when a real run had all 4 jobs fail upstream of this check and
    # still printed a misleading "OK").
    if checked == 0:
        print("  INCONCLUSIVE - 0 of the batch succeeded, nothing to check.")
    elif leaks:
        print("  LEAK CHECK FAILED:")
        for leak in leaks:
            print(f"    - {leak}")
    else:
        print(f"  OK - all {checked} edited output(s) contain exactly their own marker, no one else's.")

    print("\n--- Summary ---")
    for j in jobs:
        row = next(r for r in rows if r["id"] == j["run_id"])
        print(f"  {j['tenant_slug']:10s} run={j['run_id']}  status={row['status']:10s} "
              f"started={row['started_at']}  ended={row['ended_at']}")

    return jobs, rows, peak, leaks


if __name__ == "__main__":
    main()
