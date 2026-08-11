"""
mint_upload_urls(tenant_id, request_id, revision_number) -> {relative_path: signed_url}

Pure-ish function (one real side effect: minting URLs is a trusted-side
Storage API call, but it doesn't write any file data) that enumerates every
output file a generation run is expected to produce - three per canvas
(plate.png, overlay.html, render.png) plus RESULT.json and
agent-transcript.jsonl - and mints one signed upload URL per file, scoped
to that exact path in that tenant's own jobs bucket.

This is the orchestrator-side half of the save credential: it runs BEFORE
a sandbox exists, using the trusted service-role key (same as hydration).
The resulting URLs are what get hydrated into the sandbox as
job/upload_urls.json - from that point on, the sandbox holds only those
narrow, single-path, single-operation, time-limited tokens (verified in
Step A to require no other credential at all), never the service-role key
itself.
"""
import json
import os
import sys

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(ROOT, ".env"))
sys.path.insert(0, os.path.join(ROOT, "supabase"))

from onboarding import get_client  # noqa: E402


def _expected_output_paths(canvases):
    paths = []
    for canvas in canvases:
        name = canvas["name"]
        paths.append(f"{name}/plate.png")
        paths.append(f"{name}/overlay.html")
        paths.append(f"{name}/render.png")
    paths.append("RESULT.json")
    paths.append("agent-transcript.jsonl")
    # Heartbeat, re-uploaded (upsert) throughout the run, not just at the
    # end - lets anyone check Storage mid-run and see the agent is alive,
    # instead of only finding out at completion. See DECISIONS.md / the
    # "stuck sandbox" incident this was added in response to.
    paths.append("_status.json")
    return paths


def mint_upload_urls(tenant_id, request_id, revision_number):
    client = get_client()

    tenant = client.table("tenants").select("*").eq("id", tenant_id).single().execute().data
    request = client.table("requests").select("*").eq("id", request_id).single().execute().data
    if request["tenant_id"] != tenant["id"]:
        raise ValueError(
            f"tenant_id {tenant_id} does not own request {request_id} - refusing to mint upload URLs."
        )

    bucket = tenant["jobs_bucket"]
    prefix = f"{request_id}/revisions/{revision_number}"

    # FINDING (2026-08-10): create_signed_upload_url reserves the path even
    # before anything is uploaded to it, so minting for the same
    # request_id/revision_number twice (e.g. a retried/resumed run) collides
    # with a 409 Duplicate unless upsert is set. Retrying a run must be able
    # to re-mint the same paths without erroring - that's the whole point of
    # resume - so upsert=true is the correct default here, not an edge case.
    from storage3.types import CreateSignedUploadUrlOptions

    urls = {}
    for rel_path in _expected_output_paths(request["canvases"]):
        full_path = f"{prefix}/{rel_path}"
        signed = client.storage.from_(bucket).create_signed_upload_url(
            full_path, CreateSignedUploadUrlOptions(upsert="true")
        )
        urls[rel_path] = signed["signed_url"]

    return urls


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python upload_urls.py <tenant_id> <request_id> <revision_number>")
        sys.exit(1)
    result = mint_upload_urls(sys.argv[1], sys.argv[2], int(sys.argv[3]))
    print(f"Minted {len(result)} signed upload URLs:")
    for rel_path, url in result.items():
        print(f"  {rel_path}")
    print()
    print(json.dumps(result, indent=2))
