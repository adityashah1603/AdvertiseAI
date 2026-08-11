"""
One-time, human-run migration: renames every existing request's top-level
Storage folder from the bare request_id UUID to the new
{campaign-slug}-{short_id} convention (see worker/hydration/storage_paths.py),
inside each tenant's already-migrated jobs bucket. Companion to
migrate_bucket_naming.py, same conservative shape: copy every object to the
new path, verify file count and total bytes match exactly, only then delete
the old path. Nothing in the DB points at these paths directly (they're
always derived fresh from tenant_id/request_id/revision_number+campaign at
call time), so there is no DB row to repoint here - once the objects exist
at the new path, every future hydrate/execute/edit call already looks for
them there.

Anything at the bucket root that ISN'T a request folder (e.g. the
_connectivity_test/ folder from Step A's isolated signed-upload test) is
left alone - it doesn't match any real requests.id, so there's nothing to
rename it to.
"""
import os
import re
import sys

from dotenv import load_dotenv

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"))
sys.path.insert(0, os.path.join(ROOT, "supabase"))
sys.path.insert(0, os.path.join(ROOT, "worker", "hydration"))

from onboarding import get_client  # noqa: E402
from storage_paths import request_folder  # noqa: E402


def _list_recursive(client, bucket, prefix=""):
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


def migrate_tenant_jobs_bucket(client, tenant):
    bucket = tenant["jobs_bucket"]
    top_level = client.storage.from_(bucket).list()

    for entry in top_level:
        if entry.get("id") is not None:
            continue  # a real file at bucket root, not a request folder
        old_folder = entry["name"]

        if not _UUID_RE.match(old_folder):
            print(f"  [{tenant['slug']}] '{old_folder}' isn't a request id - leaving as-is")
            continue

        request = (
            client.table("requests").select("*").eq("id", old_folder).execute().data
        )
        if not request:
            print(f"  [{tenant['slug']}] '{old_folder}' doesn't match a request id - leaving as-is")
            continue
        request = request[0]

        new_folder = request_folder(request["campaign"], request["id"])
        if old_folder == new_folder:
            print(f"  [{tenant['slug']}] '{old_folder}' already correctly named")
            continue

        print(f"  [{tenant['slug']}] '{old_folder}' -> '{new_folder}'")
        old_files = _list_recursive(client, bucket, old_folder)
        print(f"    {len(old_files)} objects, {sum(old_files.values())} bytes")

        for i, (rel_path, _) in enumerate(old_files.items(), 1):
            suffix = rel_path[len(old_folder) + 1:]
            to_path = f"{new_folder}/{suffix}"
            client.storage.from_(bucket).copy(rel_path, to_path)
            print(f"    [{i}/{len(old_files)}] copied {suffix}")

        new_files = _list_recursive(client, bucket, new_folder)
        new_files_normalized = {f"{new_folder}/{p[len(new_folder) + 1:]}": v for p, v in new_files.items()}
        old_bytes = sum(old_files.values())
        new_bytes = sum(new_files.values())
        old_suffixes = {p[len(old_folder) + 1:] for p in old_files}
        new_suffixes = {p[len(new_folder) + 1:] for p in new_files}
        if old_suffixes != new_suffixes or old_bytes != new_bytes:
            raise RuntimeError(
                f"Verification FAILED for {tenant['slug']}/{old_folder}: "
                f"old={len(old_files)} files/{old_bytes} bytes, new={len(new_files)} files/{new_bytes} bytes. "
                f"missing={old_suffixes - new_suffixes} extra={new_suffixes - old_suffixes}. "
                f"NOT deleting old folder - it is untouched."
            )
        print(f"    VERIFIED: {len(new_files)} files, {new_bytes} bytes match exactly")

        client.storage.from_(bucket).remove(list(old_files.keys()))
        print(f"    old folder '{old_folder}' contents deleted")


def main():
    client = get_client()
    tenants = client.table("tenants").select("*").execute().data
    for tenant in tenants:
        print(f"--- {tenant['slug']} ---")
        migrate_tenant_jobs_bucket(client, tenant)
        print()
    print("Done.")


if __name__ == "__main__":
    main()
