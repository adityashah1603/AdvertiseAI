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
no request has needed one tested end-to-end). Called out explicitly rather
than silently doing nothing.

Edit runs (revision_number > 1): the prior revision's assets (plate/
overlay/render per canvas) plus any `open` comments left on it are pulled
in as job-tier data too - see `_hydrate_edit_context()`. Detected purely
from whether revision_number - 1 exists and has a succeeded run, not from
a `kind` flag threaded through by the caller - nothing about "is this an
edit" is asserted from outside; it's derived from what's actually durable.
"""
import json
import os
import sys

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(ROOT, ".env"))
sys.path.insert(0, os.path.join(ROOT, "supabase"))

from onboarding import get_client  # noqa: E402 - reuse the same client factory, not a new one
from storage_paths import revision_prefix  # noqa: E402

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


def _hydrate_edit_context(client, tenant, request, revision_number):
    """Returns (extra_files, job_context_additions) for revision_number > 1,
    or ({}, {}) if revision_number == 1 (a first-time generation, not an
    edit - nothing to pull forward).

    Deliberately requires the PRIOR revision to have an actual succeeded
    run before treating this as an editable edit - revisions.status is
    never updated by execute_run.py (only runs.status is), so a completed
    run is the only durable signal of "this revision's output really
    exists." Refusing to hydrate an edit against a prior revision that
    never finished is the same "loud, not silent" posture as the
    tenant/request mismatch check above."""
    if revision_number <= 1:
        return {}, {}

    prior_number = revision_number - 1
    prior_revision = (
        client.table("revisions")
        .select("*")
        .eq("request_id", request["id"])
        .eq("revision_number", prior_number)
        .single()
        .execute()
        .data
    )

    prior_run = (
        client.table("runs")
        .select("*")
        .eq("request_id", request["id"])
        .eq("revision_number", prior_number)
        .eq("status", "succeeded")
        .order("ended_at", desc=True)
        .limit(1)
        .execute()
        .data
    )
    if not prior_run:
        raise ValueError(
            f"revision {revision_number} is an edit of revision {prior_number}, but "
            f"revision {prior_number} has no succeeded run - refusing to hydrate an "
            f"edit against output that doesn't durably exist."
        )

    bucket = tenant["jobs_bucket"]
    prior_prefix = revision_prefix(request["campaign"], request["id"], prior_number)

    extra_files = {}
    for canvas in request["canvases"]:
        name = canvas["name"]
        for fname in ("plate.png", "overlay.html", "render.png"):
            storage_path = f"{prior_prefix}/{name}/{fname}"
            try:
                data = client.storage.from_(bucket).download(storage_path)
            except Exception as e:  # noqa: BLE001 - missing prior asset is a finding, not a crash
                extra_files[f"job/prior_revision/{name}/{fname}.MISSING.txt"] = (
                    f"Expected at {storage_path}, not found: {e}".encode("utf-8")
                )
                continue
            extra_files[f"job/prior_revision/{name}/{fname}"] = data

    open_comments = (
        client.table("comments")
        .select("*")
        .eq("revision_id", prior_revision["id"])
        .eq("status", "open")
        .order("created_at")
        .execute()
        .data
    )

    job_additions = {
        "is_edit": True,
        "prior_revision_number": prior_number,
        "comments": [
            {
                "canvas_name": c["canvas_name"],
                "region": c["region"],
                "body": c["body"],
                "author": c["author"],
            }
            for c in open_comments
        ],
    }
    return extra_files, job_additions


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
        "is_edit": False,
    }

    edit_files, edit_job_additions = _hydrate_edit_context(client, tenant, request, revision_number)
    files.update(edit_files)
    job_context.update(edit_job_additions)

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
