"""
hydrate_deploy(tenant_id, request_id, revision_number, canvas_name) -> {sandbox_path: bytes}

Phase 4's hydration function - same pure-function contract as
hydrate_generation() (generation.py): no E2B/Storage writes, no side effects,
same inputs always produce the same outputs. Deliberately thinner, per
BUILD_GUIDE.md Step 7: "No OpenAI key, no brand-kit access beyond the one
revision's final rendered assets." Unlike hydrate_generation(), this
function never touches tenant["brand_kit_bucket"] at all - there is no
brand_kit/ prefix in its output, structurally, not by convention. That
tenant tier genuinely has nothing left to contribute once a revision is
already rendered (ROADMAP.md SS4.2: "tenant tier: none needed beyond what's
already baked into the ad").

BUG FIX (2026-08-11): this used to fetch EVERY canvas on the revision and
hand them all to the agent, which then had to improvise which one(s) to
actually publish - observed for real to be inconsistent (sometimes one ad,
sometimes one per canvas), and meant an operator clicking "deploy" on the
canvas they were looking at had no way to make that the canvas that
actually got deployed - it silently deployed whatever the agent happened to
pick. Adstream genuinely only accepts one image per ad (a real, confirmed
constraint), so a deploy is now explicitly scoped to exactly one canvas,
chosen by the caller - never left to agent guesswork.

Two things get hydrated:
  1. job/creative/<canvas_name>.png - the ONE requested canvas's final
     rendered PNG for this revision, read via the assets table's own
     png_path (the same durable index execute_run.py writes on a
     successful generation/edit) - never re-derived or guessed at a path.
  2. job/request.json - campaign, copy (for the ad name/destination URL),
     and that one canvas's name/dimensions.

Nothing skill-related gets hydrated - this agent doesn't design anything,
it drives a browser, so there's no SKILL.md/tools/ here, unlike generation.

Refuses a mismatched tenant/request/revision, a revision that isn't
durably 'ready' yet, or a canvas_name with no matching asset - same
discipline as hydrate_generation() - the mechanism that makes cross-tenant
leakage structurally loud, not just unlikely, and that keeps a deploy from
ever being fired against an asset that doesn't really exist.
"""
import json
import os
import sys

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(ROOT, ".env"))
sys.path.insert(0, os.path.join(ROOT, "supabase"))

from onboarding import get_client  # noqa: E402 - reuse the same client factory, not a new one


def hydrate_deploy(tenant_id, request_id, revision_number, canvas_name):
    client = get_client()

    tenant = client.table("tenants").select("*").eq("id", tenant_id).single().execute().data
    request = client.table("requests").select("*").eq("id", request_id).single().execute().data
    revision = (
        client.table("revisions")
        .select("*")
        .eq("request_id", request_id)
        .eq("revision_number", revision_number)
        .single()
        .execute()
        .data
    )

    if request["tenant_id"] != tenant["id"]:
        raise ValueError(
            f"tenant_id {tenant_id} does not own request {request_id} "
            f"(request actually belongs to tenant {request['tenant_id']}) - refusing to hydrate."
        )
    if revision["request_id"] != request["id"]:
        raise ValueError(
            f"revision {revision_number} does not belong to request {request_id} - refusing to hydrate."
        )
    if revision["status"] != "ready":
        raise ValueError(
            f"revision {revision_number} has status '{revision['status']}', not 'ready' - "
            f"refusing to deploy an asset that doesn't durably exist yet."
        )

    asset = (
        client.table("assets")
        .select("*")
        .eq("revision_id", revision["id"])
        .eq("canvas_name", canvas_name)
        .maybe_single()
        .execute()
        .data
    )
    if not asset:
        available = [
            a["canvas_name"] for a in
            client.table("assets").select("canvas_name").eq("revision_id", revision["id"]).execute().data
        ]
        raise ValueError(
            f"canvas '{canvas_name}' has no asset on revision {revision_number} of request {request_id} "
            f"- available canvases: {available}"
        )
    if not asset.get("png_path"):
        raise ValueError(f"asset '{canvas_name}' on revision {revision_number} has no png_path - nothing to deploy.")

    bucket = tenant["jobs_bucket"]
    files = {
        f"job/creative/{canvas_name}.png": client.storage.from_(bucket).download(asset["png_path"]),
    }

    files["job/request.json"] = json.dumps({
        "request_id": request_id,
        "revision_number": revision_number,
        "campaign": request["campaign"],
        "copy": request["copy"],
        "canvas": {"name": canvas_name, "width": asset["width"], "height": asset["height"]},
    }, indent=2).encode("utf-8")

    return files


if __name__ == "__main__":
    # Quick manual smoke test: python deployment.py <tenant_id> <request_id> <revision_number> <canvas_name>
    if len(sys.argv) != 5:
        print("Usage: python deployment.py <tenant_id> <request_id> <revision_number> <canvas_name>")
        sys.exit(1)
    result = hydrate_deploy(sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4])
    print(f"Hydrated {len(result)} files:")
    for path, data in sorted(result.items()):
        print(f"  {path}  ({len(data)} bytes)")
