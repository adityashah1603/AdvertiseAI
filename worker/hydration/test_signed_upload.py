"""
Step A: verify the signed-upload-URL mechanism end to end, with NO agent
involved anywhere. Trusted service-role code mints the URL (same as
onboarding/hydration already do); the actual upload is then attempted
using ONLY the signed URL's token - deliberately no apikey/Authorization
header - to find out whether the token alone is sufficient, since that's
exactly what determines what credential the agent needs to be handed later.

Not production code - a one-off connectivity/mechanics check, deleted or
ignored after use.
"""
import os
import sys

import requests
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(ROOT, ".env"))
sys.path.insert(0, os.path.join(ROOT, "supabase"))

from onboarding import get_client  # noqa: E402

TEST_PATH = "_connectivity_test/hello.txt"
TEST_CONTENT = b"Step A connectivity test - signed upload URL mechanics.\n"


def main():
    client = get_client()

    tenant = client.table("tenants").select("*").eq("slug", "emplifi").single().execute().data
    bucket = tenant["jobs_bucket"]
    print(f"Using tenant 'emplifi', bucket '{bucket}'")

    # 1. TRUSTED side: mint a signed upload URL for one exact path.
    signed = client.storage.from_(bucket).create_signed_upload_url(TEST_PATH)
    print(f"Minted signed URL for '{TEST_PATH}':")
    print(f"  {signed['signed_url']}")
    print(f"  token: {signed['token'][:20]}...")

    # 2. UNTRUSTED side: upload using ONLY the token from the signed URL -
    #    no apikey, no Authorization header, nothing else. This is exactly
    #    what an agent holding only this URL would be able to do.
    upload_url = signed["signed_url"]
    print(f"\nAttempting upload with ONLY the signed URL, no API key header...")
    resp = requests.put(
        upload_url,
        files={"file": ("hello.txt", TEST_CONTENT, "text/plain")},
    )
    print(f"  status: {resp.status_code}")
    print(f"  body:   {resp.text[:300]}")

    if resp.status_code not in (200, 201):
        print("\nFAILED with token-only auth. Retrying WITH the anon key added, to see if that's what's required...")
        anon_key = os.environ.get("SUPABASE_ANON_KEY", "")
        resp2 = requests.put(
            upload_url,
            files={"file": ("hello.txt", TEST_CONTENT, "text/plain")},
            headers={"apikey": anon_key, "Authorization": f"Bearer {anon_key}"} if anon_key else {},
        )
        print(f"  status with anon key: {resp2.status_code}")
        print(f"  body:   {resp2.text[:300]}")

    # 3. Independent verification: read it back using the TRUSTED client,
    #    not by trusting the upload response's status code alone.
    print("\nIndependently verifying via trusted client...")
    downloaded = client.storage.from_(bucket).download(TEST_PATH)
    print(f"  downloaded {len(downloaded)} bytes")
    print(f"  content matches: {downloaded == TEST_CONTENT}")


if __name__ == "__main__":
    main()
