"""
One-time, human-run migration: renames every existing tenant's Storage
buckets from the old brand-kit-{tenant_id}/jobs-{tenant_id} convention to
the new brandkit-{slug}-{short_id}/jobs-{slug}-{short_id} one (see
onboarding.py's onboard_tenant() for why). Not something a real system
would run again - onboard_tenant() already creates new tenants correctly
named; this exists only to bring Emplifi/Kahua/Duolingo's already-live
buckets in line, without losing any of the real generated output already
sitting in them (Phase 1 confirmation runs, the concurrency test, the edit
test).

Deliberately conservative about the one truly irreversible step: copies
every object to the new bucket using Supabase Storage's own server-side
cross-bucket copy (no data transferred through this machine), verifies the
new bucket's file count and total bytes match the old bucket's exactly,
and only THEN repoints tenants.brand_kit_bucket/jobs_bucket at the new
name. It does NOT delete the old buckets - that's a separate, explicit
second step (delete_old_buckets()) run only after a human has looked at
the verification output.
"""
import os
import sys

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"))
sys.path.insert(0, os.path.join(ROOT, "supabase"))

from onboarding import get_client  # noqa: E402


def _list_recursive(client, bucket, prefix=""):
    """Returns {relative_path: size_in_bytes} for every real file in a
    bucket (folders are markers with id=None, not real objects)."""
    files = {}
    entries = client.storage.from_(bucket).list(prefix or None)
    for entry in entries:
        rel_path = f"{prefix}/{entry['name']}" if prefix else entry["name"]
        if entry.get("id") is None:
            files.update(_list_recursive(client, bucket, rel_path))
        else:
            size = (entry.get("metadata") or {}).get("size", -1)
            files[rel_path] = size
    return files


def _server_side_copy(client, from_bucket, to_bucket, path):
    """Supabase Storage's copy endpoint supports an optional
    destinationBucket field for cross-bucket copies - not exposed by this
    version of the storage3 client's copy() wrapper (same-bucket only), so
    this calls the same underlying _request() the wrapper itself uses,
    with that one extra field added."""
    proxy = client.storage.from_(from_bucket)
    proxy._request(
        "POST",
        ["object", "copy"],
        json={
            "bucketId": from_bucket,
            "sourceKey": path,
            "destinationKey": path,
            "destinationBucket": to_bucket,
        },
    )


def migrate_tenant_buckets(client, tenant):
    slug = tenant["slug"]
    tenant_id = tenant["id"]
    short_id = tenant_id.split("-")[0]

    plan = [
        ("brand_kit_bucket", tenant["brand_kit_bucket"], f"brandkit-{slug}-{short_id}"),
        ("jobs_bucket", tenant["jobs_bucket"], f"jobs-{slug}-{short_id}"),
    ]

    updates = {}
    for column, old_bucket, new_bucket in plan:
        if old_bucket == new_bucket:
            print(f"  [{slug}] {column}: already '{new_bucket}', nothing to do")
            continue

        print(f"  [{slug}] {column}: '{old_bucket}' -> '{new_bucket}'")

        old_files = _list_recursive(client, old_bucket)
        print(f"    {len(old_files)} objects, {sum(old_files.values())} bytes total in old bucket")

        try:
            client.storage.create_bucket(new_bucket, options={"public": False})
        except Exception as e:
            if "already exists" not in str(e).lower() and "Duplicate" not in str(e):
                raise
            print(f"    bucket '{new_bucket}' already exists (partial prior run?) - continuing")

        for i, path in enumerate(old_files, 1):
            _server_side_copy(client, old_bucket, new_bucket, path)
            print(f"    [{i}/{len(old_files)}] copied {path}")

        new_files = _list_recursive(client, new_bucket)
        old_bytes = sum(old_files.values())
        new_bytes = sum(new_files.values())
        if set(new_files) != set(old_files) or old_bytes != new_bytes:
            missing = set(old_files) - set(new_files)
            extra = set(new_files) - set(old_files)
            raise RuntimeError(
                f"Verification FAILED for {slug}/{column}: "
                f"old={len(old_files)} files/{old_bytes} bytes, "
                f"new={len(new_files)} files/{new_bytes} bytes. "
                f"missing={missing} extra={extra}. "
                f"NOT repointing the DB - old bucket '{old_bucket}' is untouched."
            )
        print(f"    VERIFIED: {len(new_files)} files, {new_bytes} bytes match exactly")

        updates[column] = new_bucket

    if updates:
        client.table("tenants").update(updates).eq("id", tenant_id).execute()
        print(f"  [{slug}] tenants row updated: {updates}")

    return updates


def main():
    client = get_client()
    tenants = client.table("tenants").select("*").execute().data
    print(f"Found {len(tenants)} tenants.\n")

    all_updates = {}
    for tenant in tenants:
        print(f"--- {tenant['slug']} ({tenant['id']}) ---")
        updates = migrate_tenant_buckets(client, tenant)
        if updates:
            all_updates[tenant["slug"]] = {
                "old": {
                    "brand_kit_bucket": tenant["brand_kit_bucket"],
                    "jobs_bucket": tenant["jobs_bucket"],
                },
                "new": updates,
            }
        print()

    print("=== Done. Old buckets were NOT deleted. ===")
    for slug, info in all_updates.items():
        print(f"{slug}: old buckets now orphaned (safe to delete once you've confirmed the new ones look right):")
        for k, v in info["old"].items():
            print(f"    {v}")


if __name__ == "__main__":
    main()
