"""
hydrate_deploy(tenant_id, request_id, revision_number) -> {sandbox_path: bytes}

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

Three things get hydrated:
  1. job/creative/<canvas_name>.png - each canvas's final rendered PNG for
     this revision, read via the assets table's own png_path (the same
     durable index execute_run.py writes on a successful generation/edit) -
     never re-derived or guessed at a path.
  2. job/request.json - campaign, copy (for the ad name/destination URL),
     and the canvas list, so the agent knows what it's supposed to have
     uploaded before it's done.
  3. Nothing skill-related - this agent doesn't design anything, it drives a
     browser, so there's no SKILL.md/tools/ to hydrate, unlike generation.

Refuses a mismatched tenant/request/revision, or a revision that isn't
durably 'ready' yet, same discipline as hydrate_generation() - the mechanism
that makes cross-tenant leakage structurally loud, not just unlikely, and
that keeps a deploy from ever being fired against an asset that doesn't
really exist.
"""
import json
import os
import sys

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(ROOT, ".env"))
sys.path.insert(0, os.path.join(ROOT, "supabase"))

from onboarding import get_client  # noqa: E402 - reuse the same client factory, not a new one


def hydrate_deploy(tenant_id, request_id, revision_number):
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

    assets = (
        client.table("assets")
        .select("*")
        .eq("revision_id", revision["id"])
        .execute()
        .data
    )
    if not assets:
        raise ValueError(f"revision {revision_number} of request {request_id} has no assets rows - nothing to deploy.")

    bucket = tenant["jobs_bucket"]
    files = {}
    canvases = []
    for asset in assets:
        name = asset["canvas_name"]
        if not asset.get("png_path"):
            raise ValueError(f"asset '{name}' on revision {revision_number} has no png_path - nothing to deploy.")
        files[f"job/creative/{name}.png"] = client.storage.from_(bucket).download(asset["png_path"])
        canvases.append({"name": name, "width": asset["width"], "height": asset["height"]})

    files["job/request.json"] = json.dumps({
        "request_id": request_id,
        "revision_number": revision_number,
        "campaign": request["campaign"],
        "copy": request["copy"],
        "canvases": canvases,
    }, indent=2).encode("utf-8")

    return files


if __name__ == "__main__":
    # Quick manual smoke test: python deployment.py <tenant_id> <request_id> <revision_number>
    if len(sys.argv) != 4:
        print("Usage: python deployment.py <tenant_id> <request_id> <revision_number>")
        sys.exit(1)
    result = hydrate_deploy(sys.argv[1], sys.argv[2], int(sys.argv[3]))
    print(f"Hydrated {len(result)} files:")
    for path, data in sorted(result.items()):
        print(f"  {path}  ({len(data)} bytes)")
