"""
One-time backfill, companion to onboarding.py's new inspirations_bucket:

  1. Ensures every existing tenant has an inspirations_bucket (via
     onboard_tenant()'s idempotent backfill path - safe to call repeatedly,
     never re-creates or touches an already-set bucket).
  2. Uploads this repo's legacy inspirations/*.png files into
     the matching tenant's new bucket, matched by filename prefix
     (emplifi-* -> emplifi, kahua-* -> kahua).

Step 2's filename-prefix matching is legacy-fixture-specific glue,
deliberately kept out of onboard_tenant() itself - a real new brand's
onboarding path (the frontend's /onboard form) never depends on this
repo's own inspirations/ folder; that folder only exists because the brief
shipped it as reference data for Emplifi/Kahua.

Usage:
    python backfill_inspirations.py
"""
import os
import sys

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"))
sys.path.insert(0, os.path.join(ROOT, "supabase"))

from onboarding import get_client, onboard_tenant  # noqa: E402

LEGACY_INSPIRATIONS_DIR = os.path.join(ROOT, "inspirations")


def main():
    client = get_client()
    tenants = client.table("tenants").select("*").execute().data
    print(f"Found {len(tenants)} tenant(s).\n")

    legacy_files = []
    if os.path.isdir(LEGACY_INSPIRATIONS_DIR):
        legacy_files = [
            f for f in os.listdir(LEGACY_INSPIRATIONS_DIR)
            if os.path.isfile(os.path.join(LEGACY_INSPIRATIONS_DIR, f))
        ]
    else:
        print(f"WARNING: {LEGACY_INSPIRATIONS_DIR} not found - bucket backfill only, no uploads.\n")

    for tenant in tenants:
        slug = tenant["slug"]
        print(f"--- {slug} ---")
        result = onboard_tenant(client, slug, tenant["name"])
        bucket = result["inspirations_bucket"]

        matches = [f for f in legacy_files if f.startswith(f"{slug}-")]
        if not matches:
            print(f"  no legacy inspiration files match prefix '{slug}-'")
            print()
            continue
        for fname in matches:
            full_path = os.path.join(LEGACY_INSPIRATIONS_DIR, fname)
            with open(full_path, "rb") as fh:
                data = fh.read()
            client.storage.from_(bucket).upload(fname, data, {"upsert": "true"})
            print(f"  uploaded {fname} -> {bucket}")
        print()

    print("Done.")


if __name__ == "__main__":
    main()
