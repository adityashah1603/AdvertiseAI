"""
Local preflight check for BUILD_GUIDE.md Step 0.

Runs on YOUR machine, not inside a sandbox. Its only job is to tell you,
before any real building starts, which of the credentials in .env are
actually present and actually work. It never creates billable resources
(no sandbox is spun up, no image is generated, no browser session is
opened) — every check here is a cheap, read-only auth probe.

Usage:
    cd scripts
    python -m venv .venv && .venv/Scripts/activate   (or source .venv/bin/activate)
    pip install -r requirements.txt
    python check_env.py
"""

import os
import sys

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"))

results = []


def record(name, status, detail):
    results.append((name, status, detail))


def check_present(name, *var_names):
    """For services with no cheap/known-safe API probe: just confirm the
    variable(s) are non-empty, and say so plainly rather than pretending to
    have verified more than that."""
    missing = [v for v in var_names if not os.environ.get(v)]
    if missing:
        record(name, "NOT CONFIGURED", f"missing: {', '.join(missing)}")
    else:
        record(name, "PRESENT", "value(s) set - not programmatically verified, see comment in source")


def check_anthropic():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return record("Anthropic", "NOT CONFIGURED", "ANTHROPIC_API_KEY is empty")
    try:
        import anthropic
    except ImportError:
        return record("Anthropic", "SKIPPED", "pip install -r requirements.txt first")
    try:
        client = anthropic.Anthropic(api_key=key)
        client.models.list(limit=1)
        record("Anthropic", "OK", "key authenticates")
    except Exception as e:
        record("Anthropic", "FAIL", str(e)[:200])


def check_openai():
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return record("OpenAI", "NOT CONFIGURED", "OPENAI_API_KEY is empty")
    try:
        import openai
    except ImportError:
        return record("OpenAI", "SKIPPED", "pip install -r requirements.txt first")
    try:
        client = openai.OpenAI(api_key=key)
        client.models.list()
        record("OpenAI", "OK", "key authenticates")
    except Exception as e:
        record("OpenAI", "FAIL", str(e)[:200])


def check_e2b():
    key = os.environ.get("E2B_API_KEY")
    if not key:
        return record("E2B", "NOT CONFIGURED", "E2B_API_KEY is empty")
    try:
        from e2b import Sandbox
    except ImportError:
        return record("E2B", "SKIPPED", "pip install -r requirements.txt first")
    try:
        # Sandbox.list() only reads account state — it does not start one.
        Sandbox.list(api_key=key)
        record("E2B", "OK", "key authenticates")
    except AttributeError:
        record("E2B", "PRESENT", "key is set but this SDK version has no list() to probe with - verify manually (e.g. `e2b sandbox list`)")
    except Exception as e:
        record("E2B", "FAIL", str(e)[:200])


def check_kernel():
    # No verified-safe, version-stable probe call is hardcoded here on
    # purpose — confirm the exact lightweight auth check against
    # docs.onkernel.com when Step 7 (deployment sandbox) is built, rather
    # than guess at an SDK method now.
    check_present("Kernel", "KERNEL_API_KEY")


def check_supabase():
    url = os.environ.get("SUPABASE_URL")
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not service_key:
        missing = [n for n, v in [("SUPABASE_URL", url), ("SUPABASE_SERVICE_ROLE_KEY", service_key)] if not v]
        return record("Supabase", "NOT CONFIGURED", f"missing: {', '.join(missing)}")
    try:
        import requests
    except ImportError:
        return record("Supabase", "SKIPPED", "pip install -r requirements.txt first")
    try:
        # REST root responds with the project's OpenAPI schema for a valid
        # key — no table needs to exist yet (schema lands in Step 2).
        resp = requests.get(
            f"{url.rstrip('/')}/rest/v1/",
            headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"},
            timeout=10,
        )
        if resp.status_code == 200:
            record("Supabase", "OK", "key authenticates against REST root")
        else:
            record("Supabase", "FAIL", f"HTTP {resp.status_code}: {resp.text[:150]}")
    except Exception as e:
        record("Supabase", "FAIL", str(e)[:200])


def check_adstream():
    check_present("Adstream", "ADSTREAM_LOGIN_URL", "ADSTREAM_EMAIL", "ADSTREAM_PASSWORD")


def main():
    check_anthropic()
    check_openai()
    check_e2b()
    check_kernel()
    check_supabase()
    check_adstream()

    name_w = max(len(n) for n, _, _ in results)
    status_w = max(len(s) for _, s, _ in results)
    print()
    for name, status, detail in results:
        print(f"{name.ljust(name_w)}  {status.ljust(status_w)}  {detail}")
    print()

    if any(status == "FAIL" for _, status, _ in results):
        print("At least one configured credential failed to authenticate. Fix before Step 1.")
        sys.exit(1)
    if any(status == "NOT CONFIGURED" for _, status, _ in results):
        print("Some credentials aren't set yet - expected until the CEO call resolves access. "
              "Nothing below Step 0 needs them yet.")
        sys.exit(0)
    print("All credentials present. Note: PRESENT/SKIPPED entries above were not "
          "programmatically verified - see the comments in this script for why.")


if __name__ == "__main__":
    main()
