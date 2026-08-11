"""
The one real implementation of "bring a new tenant into the system."

This is NOT a one-off script - it's the shared capability both the
bootstrap CLI (supabase/seed/seed.py, for Emplifi/Kahua/Duolingo today) and
the future backend endpoint (for the real "a new brand is given in the UI"
flow the brief actually tests) call. Writing it once here, and having both
callers use it, is what makes "zero code changes for a new brand" true - if
the CLI and the real API onboarding path were two different implementations,
they'd drift, and the day-two brand would be exercising a path nobody
actually tested.

What onboarding a tenant means, concretely:
  1. Insert a `tenants` row (idempotent by slug - re-onboarding an existing
     slug reuses its id/buckets rather than duplicating).
  2. Create two Storage buckets scoped to this tenant alone:
     brandkit-{slug}-{short_id} and jobs-{slug}-{short_id}. Per-tenant
     buckets, not a shared bucket with a tenant_id-prefixed path - see
     DECISIONS.md for the reasoning (a bug in one tenant's bucket setup
     stays contained to that bucket, rather than one shared policy
     protecting everyone at once). Named with the tenant's own slug (not
     just a bare UUID) so a human scanning the Storage dashboard can tell
     whose data a bucket holds without cross-referencing the `tenants`
     table - the {short_id} suffix (the tenant id's own first 8 hex
     characters) exists only for guaranteed uniqueness if a slug were ever
     reused, never for lookup: every place that actually NEEDS a bucket
     name reads it from `tenants.brand_kit_bucket`/`jobs_bucket`, never
     reconstructs it from the slug. This is cosmetic/organizational, not a
     sandbox-identity concern - ROADMAP.md's "no tenant-specific identity"
     disqualifier is explicitly about a SANDBOX's image/template/name/id,
     not about how tenant-scoped Storage buckets (already tenant-specific
     by design) happen to be labeled.
  3. If brand-kit files are given, upload them into the brand-kit bucket -
     at the bucket root now, not under a tenant_id prefix, since the
     bucket itself is the isolation boundary.
  4. Leave the jobs bucket empty - that's populated per run, by the agent,
     not at onboarding time.

Deliberately NOT built here: brand-kit versioning, re-upload history, or
validation that rejects an incomplete brand kit. Real brand kits are
incomplete (see phase0/README.md's findings on Kahua's missing font and
logo) - onboarding accepts what it's given and lets hydration's existing
omit-don't-fake behavior handle gaps at generation time, not at intake time.
"""
import os


UPLOAD_SUBPATHS = ["DESIGN.md", "fonts", "brand"]


def get_client():
    import sys

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set - nothing to do.", file=sys.stderr)
        sys.exit(1)
    from supabase import create_client
    return create_client(url, key)


def _iter_files(local_dir, subpaths):
    for subpath in subpaths:
        full = os.path.join(local_dir, subpath)
        if os.path.isfile(full):
            yield subpath, full
        elif os.path.isdir(full):
            for dirpath, _, filenames in os.walk(full):
                for fname in filenames:
                    abs_path = os.path.join(dirpath, fname)
                    rel_path = os.path.relpath(abs_path, local_dir).replace(os.sep, "/")
                    yield rel_path, abs_path


def _upload_brand_kit(client, bucket, local_dir):
    count = 0
    for rel_path, abs_path in _iter_files(local_dir, UPLOAD_SUBPATHS):
        with open(abs_path, "rb") as f:
            data = f.read()
        client.storage.from_(bucket).upload(rel_path, data, {"upsert": "true"})
        count += 1
    return count


def onboard_tenant(client, slug, name, local_brand_kit_dir=None):
    """Returns {"id", "brand_kit_bucket", "jobs_bucket"} for the tenant,
    whether it was just created or already existed."""
    existing = client.table("tenants").select("*").eq("slug", slug).execute()

    if existing.data:
        tenant = existing.data[0]
        tenant_id = tenant["id"]
        brand_kit_bucket = tenant["brand_kit_bucket"]
        jobs_bucket = tenant["jobs_bucket"]
        print(f"Tenant '{slug}' already exists: {tenant_id}")
    else:
        result = client.table("tenants").insert({"slug": slug, "name": name}).execute()
        tenant_id = result.data[0]["id"]
        short_id = tenant_id.split("-")[0]  # UUID's own first 8 hex chars - no new id invented
        brand_kit_bucket = f"brandkit-{slug}-{short_id}"
        jobs_bucket = f"jobs-{slug}-{short_id}"

        client.storage.create_bucket(brand_kit_bucket, options={"public": False})
        client.storage.create_bucket(jobs_bucket, options={"public": False})

        client.table("tenants").update({
            "brand_kit_bucket": brand_kit_bucket,
            "jobs_bucket": jobs_bucket,
        }).eq("id", tenant_id).execute()

        print(f"Created tenant '{slug}': {tenant_id}")
        print(f"  brand_kit_bucket: {brand_kit_bucket}")
        print(f"  jobs_bucket:      {jobs_bucket}")

    if local_brand_kit_dir and os.path.isdir(local_brand_kit_dir):
        count = _upload_brand_kit(client, brand_kit_bucket, local_brand_kit_dir)
        print(f"  Uploaded {count} files to bucket '{brand_kit_bucket}'")

    return {"id": tenant_id, "brand_kit_bucket": brand_kit_bucket, "jobs_bucket": jobs_bucket}
