"""
hydrate_generation(tenant_id, request_id, revision_number) -> {sandbox_path: bytes}

A pure function - it does not touch E2B, does not create a sandbox, does
not write anything anywhere. Given three ids, it returns exactly the file
set a fresh generation sandbox needs, fetched fresh every single call:

  1. Global tier  - SKILL.md + the tool scripts, read from this repo.
     Identical for every run, every tenant - carries no tenant/task
     identity, so it's fine for this to come from a fixed local path
     rather than Storage (ROADMAP.md SS3.2).
  2. Tenant tier   - that tenant's DESIGN.md/fonts/brand assets, fetched
     from THEIR OWN brand_kit_bucket (looked up from the tenants row this
     call reads - never assumed, never cached from a prior call).
  3. Job tier      - that request's copy/canvases, as JSON.

This being a pure function is what makes resume trivial: rehydrating
revision 3 after revision 4 failed is calling this again with
revision_number=3. Same inputs, same outputs, no sandbox-specific state
required anywhere (ROADMAP.md SS6).

NOT yet implemented: fetching actual inspiration image files (the
`inspirations` list is passed through in job/request.json, but the
referenced files aren't fetched - there's no inspirations bucket yet, and
no request has needed one tested end-to-end). NOT yet implemented: prior
revision's assets / open comments for an edit run (comments don't exist
until Step 6). Both are called out explicitly rather than silently doing
nothing.
"""
import json
import os
import sys

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(ROOT, ".env"))
sys.path.insert(0, os.path.join(ROOT, "supabase"))

from onboarding import get_client  # noqa: E402 - reuse the same client factory, not a new one

GENERATION_SKILL_FILES = {
    "skill/SKILL.md": os.path.join(ROOT, "SKILL.md"),
    "skill/tools/call_gpt_image.py": os.path.join(
        ROOT, "worker", "sandbox_images", "generation", "tools", "call_gpt_image.py"
    ),
    "skill/tools/render_html.py": os.path.join(
        ROOT, "worker", "sandbox_images", "generation", "tools", "render_html.py"
    ),
}


def _read_local(path):
    with open(path, "rb") as f:
        return f.read()


def _fetch_bucket_recursive(client, bucket, prefix=""):
    """Walks a Storage bucket and returns {relative_path: bytes} for every
    file in it. Supabase Storage's list() returns one level at a time and
    marks folders with id=None, so folders need a recursive call."""
    files = {}
    entries = client.storage.from_(bucket).list(prefix or None)
    for entry in entries:
        name = entry["name"]
        rel_path = f"{prefix}/{name}" if prefix else name
        if entry.get("id") is None:
            files.update(_fetch_bucket_recursive(client, bucket, rel_path))
        else:
            files[rel_path] = client.storage.from_(bucket).download(rel_path)
    return files


def hydrate_generation(tenant_id, request_id, revision_number):
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

    # Refuse to hydrate a mismatched combination rather than silently using
    # whichever tenant/request the caller happened to pass - this is the
    # kind of check that makes cross-tenant contamination structurally
    # loud instead of quiet.
    if request["tenant_id"] != tenant["id"]:
        raise ValueError(
            f"tenant_id {tenant_id} does not own request {request_id} "
            f"(request actually belongs to tenant {request['tenant_id']}) - refusing to hydrate."
        )
    if revision["request_id"] != request["id"]:
        raise ValueError(
            f"revision {revision_number} does not belong to request {request_id} - refusing to hydrate."
        )

    files = {}

    for sandbox_path, local_path in GENERATION_SKILL_FILES.items():
        files[sandbox_path] = _read_local(local_path)

    # Prefixed "brand_kit/" (not "brand/") on purpose - the brain's own
    # layout already has an inner brand/ subfolder (manifest, logos,
    # tokens.json, alongside root-level DESIGN.md and fonts/), so a "brand/"
    # outer prefix here would collide into a confusing brand/brand/... path.
    # brand_kit/ also matches the tenants.brand_kit_bucket column name this
    # data actually came from.
    brand_kit_files = _fetch_bucket_recursive(client, tenant["brand_kit_bucket"])
    for rel_path, data in brand_kit_files.items():
        files[f"brand_kit/{rel_path}"] = data

    job_context = {
        "request_id": request_id,
        "revision_number": revision_number,
        "campaign": request["campaign"],
        "copy": request["copy"],
        "canvases": request["canvases"],
        "inspirations": request["inspirations"],
    }
    files["job/request.json"] = json.dumps(job_context, indent=2).encode("utf-8")

    return files


if __name__ == "__main__":
    # Quick manual smoke test: python generation.py <tenant_id> <request_id> <revision_number>
    if len(sys.argv) != 4:
        print("Usage: python generation.py <tenant_id> <request_id> <revision_number>")
        sys.exit(1)
    result = hydrate_generation(sys.argv[1], sys.argv[2], int(sys.argv[3]))
    print(f"Hydrated {len(result)} files:")
    for path, data in sorted(result.items()):
        print(f"  {path}  ({len(data)} bytes)")
