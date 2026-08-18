"""
Bootstraps the three brands this project already has: Emplifi, Kahua
(from design-brains/), and the Duolingo generalization test
(from third-brand-test/).

This script is NOT the real onboarding path - it's a thin CLI wrapper
around supabase/onboarding.py's onboard_tenant(), the one shared
implementation a future backend endpoint will call for the real "a new
brand shows up in the UI" flow. Using the same function here means this
script exercises the exact same path the real day-two test will use,
instead of a parallel implementation that could quietly drift from it.

Usage:
    cd supabase/seed
    python -m venv .venv && .venv/Scripts/activate
    pip install -r requirements.txt
    python seed.py
"""
import os
import sys

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(ROOT, ".env"))
sys.path.insert(0, os.path.join(ROOT, "supabase"))

from onboarding import get_client, onboard_tenant  # noqa: E402

BRANDS = [
    {
        "slug": "emplifi",
        "name": "Emplifi",
        "local_dir": os.path.join(ROOT, "design-brains", "emplifi"),
    },
    {
        "slug": "kahua",
        "name": "Kahua",
        "local_dir": os.path.join(ROOT, "design-brains", "kahua"),
    },
    {
        "slug": "duolingo",
        "name": "Duolingo (generalization test brand)",
        "local_dir": os.path.join(ROOT, "third-brand-test", "duolingo"),
    },
]


def main():
    client = get_client()
    print()
    for brand in BRANDS:
        if not os.path.isdir(brand["local_dir"]):
            print(f"SKIP '{brand['slug']}': local dir not found: {brand['local_dir']}", file=sys.stderr)
            continue
        onboard_tenant(client, brand["slug"], brand["name"], brand["local_dir"])
        print()
    print("Done.")


if __name__ == "__main__":
    main()
