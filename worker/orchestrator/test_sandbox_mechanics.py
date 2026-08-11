"""
Step B: verify E2B sandbox mechanics in isolation. NO agent involved -
just create a real sandbox, write real hydration data into it, run a
harmless verification command inside it, confirm the files survived
intact, then destroy it.

Not production code - this is a one-off mechanics check, the same role
test_signed_upload.py played for Step A. The real orchestrator (built
after this) reuses the same e2b.Sandbox calls verified here, but with
agent_runner.py as the command instead of a `find`/checksum probe.

Constraint notes:
  - No tenant-identifying metadata is passed to create_sandbox()
    (sandbox_factory.py) - the sandbox is anonymous, exactly as the
    disqualifiers require. Its id (printed below) is whatever opaque
    string E2B issues.
  - The only things read back from the sandbox here are command
    stdout/stderr from a diagnostic probe (a file listing and a checksum),
    not any agent's creative output - there is no agent and no creative
    output in this step. That's a deliberately different category from
    the disqualified "backend reads the sandbox's filesystem to collect
    the agent's results" - this is a health check on the plumbing itself,
    run before there's any real work to leak.
"""
import hashlib
import os
import sys

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(ROOT, ".env"))
sys.path.insert(0, os.path.join(ROOT, "worker", "hydration"))

# Same shared helper execute_run.py uses - see sandbox_factory.py. This
# script used to call `Sandbox.create(...)` directly, a second independent
# call site carrying the exact same broken-API bug found in execute_run.py.
from sandbox_factory import create_sandbox  # noqa: E402

# worker/hydration's own venv has `supabase` installed; this venv doesn't
# yet - reuse that one's site-packages rather than duplicating the install.
HYDRATION_VENV_SITE_PACKAGES = os.path.join(
    ROOT, "worker", "hydration", ".venv", "Lib", "site-packages"
)
sys.path.insert(0, HYDRATION_VENV_SITE_PACKAGES)

from generation import hydrate_generation  # noqa: E402

TENANT_ID = "e3b04af1-2fc4-4a5a-a5ff-71155859f96a"  # emplifi
REQUEST_ID = "5f3b4b97-19a7-435e-bfea-55c0f66dda03"


def main():
    print("Hydrating real files (same as Step A/hydration testing)...")
    files = hydrate_generation(TENANT_ID, REQUEST_ID, 1)
    print(f"  {len(files)} files ready to write into a sandbox\n")

    local_skill_md_hash = hashlib.sha256(files["skill/SKILL.md"]).hexdigest()

    print("Creating a fresh E2B sandbox (no tenant-identifying metadata)...")
    sbx = create_sandbox(timeout=120)
    print(f"  sandbox_id: {sbx.sandbox_id}  <- opaque, provider-issued, not a tenant/task name\n")

    try:
        print("Writing all hydrated files into the sandbox...")
        for rel_path, data in files.items():
            sbx.files.write(rel_path, data)
        print(f"  wrote {len(files)} files\n")

        print("Running a harmless verification probe inside the sandbox...")
        listing = sbx.commands.run("find . -type f | sort")
        print("  --- find . -type f ---")
        print("  " + listing.stdout.replace("\n", "\n  ").strip())

        checksum_cmd = sbx.commands.run("sha256sum skill/SKILL.md")
        print("\n  --- sha256sum skill/SKILL.md (inside sandbox) ---")
        print("  " + checksum_cmd.stdout.strip())
        remote_hash = checksum_cmd.stdout.strip().split()[0]

        version_cmd = sbx.commands.run("python3 --version")
        print("\n  --- python3 --version ---")
        print("  " + version_cmd.stdout.strip() + version_cmd.stderr.strip())

        print(f"\nLocal SHA256 of skill/SKILL.md:  {local_skill_md_hash}")
        print(f"Sandbox SHA256 of skill/SKILL.md: {remote_hash}")
        print(f"Match: {local_skill_md_hash == remote_hash}")

    finally:
        print(f"\nDestroying sandbox {sbx.sandbox_id}...")
        sbx.kill()
        print("Destroyed.")


if __name__ == "__main__":
    main()
