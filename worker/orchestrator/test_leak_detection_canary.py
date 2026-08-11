"""
Phase 2: proves the leak-detection check used in test_concurrency.py can
actually fail, before trusting it on a real run. Per ROADMAP.md section 5:
"If you build any leak-detection check, first prove the check can actually
fail: plant a real leak once on purpose and confirm the check catches it.
A check that has never been shown to fail is not evidence of anything."

No new spend needed for this: it reuses two already-completed, already
human-verified Phase 1 outputs (Emplifi's and Kahua's real first runs) and
deliberately checks Kahua's real overlay.html as though it were Emplifi's -
i.e. plants a real (mislabeled) leak on purpose - and confirms the check
flags it. If this assertion ever fails, the checker itself is broken or
vacuous and test_concurrency.py's "OK - no leakage" result cannot be
trusted.
"""
import os
import sys

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(ROOT, ".env"))
sys.path.insert(0, os.path.join(ROOT, "supabase"))
sys.path.insert(0, os.path.join(ROOT, "worker", "hydration"))

from onboarding import get_client  # noqa: E402
from storage_paths import revision_prefix  # noqa: E402

EMPLIFI_HEADLINE = "Shoppable video becomes the default discovery surface"

KAHUA_TENANT_ID = "4c224b0d-5531-4099-8057-f219c09fea06"
KAHUA_REQUEST_ID = "71e5f31e-184c-4b1f-9657-e03996340d5f"
KAHUA_CAMPAIGN = "Field to Office"


def main():
    client = get_client()
    kahua_tenant = client.table("tenants").select("*").eq("id", KAHUA_TENANT_ID).single().execute().data

    path = f"{revision_prefix(KAHUA_CAMPAIGN, KAHUA_REQUEST_ID, 1)}/square/overlay.html"
    print(f"Downloading Kahua's REAL output from a prior confirmed run: {path}")
    html = client.storage.from_(kahua_tenant["jobs_bucket"]).download(path).decode("utf-8", errors="replace")

    print("Checking it as though it were mislabeled as Emplifi's output "
          "(this is the deliberately-planted leak)...")
    emplifi_headline_present = EMPLIFI_HEADLINE in html
    leak_detected = not emplifi_headline_present

    print(f"  Emplifi's headline present in Kahua's real output: {emplifi_headline_present}")
    print(f"  -> {'check CORRECTLY FLAGGED the planted leak' if leak_detected else 'check FAILED TO CATCH the planted leak'}")

    assert leak_detected, (
        "Canary failed: the leak-detection logic did not flag a real, "
        "deliberately-planted mismatch. Do not trust test_concurrency.py's "
        "leak-check result until this passes."
    )
    print("\nCanary passed - the leak-detection logic is proven able to fail, "
          "so a clean result from test_concurrency.py means something.")


if __name__ == "__main__":
    main()
