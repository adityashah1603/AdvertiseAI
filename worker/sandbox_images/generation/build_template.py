"""
Builds the reusable E2B template for generation sandboxes: a Python base
image with our dependencies (Playwright + Chromium included) pre-installed.

This is a ONE-TIME (or rare, when dependencies change) setup step, run by a
human, exactly like the Supabase migration was - not something the
orchestrator runs per request.

Rule check (see conversation record / DECISIONS.md): pre-baking runtime
dependencies into a template does not violate the "clean box" disqualifier.
The brief's own hydration model already assumes tooling is present
("imagine SSHing into the box, typing `claude`... and walking away"), and
the disqualifier is specifically about a box's IDENTITY revealing which
tenant/task it serves - this template is identical for Emplifi, Kahua,
Duolingo, or any future brand. Zero tenant/task identity baked in, only
software.

Deliberately NOT baked into this template: agent_runner.py, call_gpt_image.py,
render_html.py. Those are still actively being developed/iterated on, and
baking them in would mean rebuilding this template every time one changes -
the orchestrator continues to write them in fresh each run (cheap - they're
small text files, not the expensive part). Only the heavy, stable,
rarely-changing dependencies live in the template.

Started at the FREE-TIER-COMPATIBLE default size (memory_mb=1024,
cpu_count=2) on purpose - per the E2B pricing research, only paid plans can
customize sandbox CPU/RAM at all, so this first attempt tests whether
pre-installing dependencies at build time (rather than under time pressure
at every run) resolves the memory issue on its own, before spending
anything on a plan upgrade.

Usage:
    python build_template.py
"""
import os
import sys

from dotenv import load_dotenv
from e2b import Template

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
load_dotenv(os.path.join(ROOT, ".env"))

TEMPLATE_ALIAS = "cq-generation-v1"


def main():
    # FINDING (2026-08-10): starting from a bare python:3.11 image and running
    # `playwright install chromium --with-deps` fails - Playwright's dependency
    # installer targets Ubuntu package names (e.g. ttf-ubuntu-font-family)
    # that don't exist under this image's Debian "trixie" base. Using
    # Microsoft's own official Playwright+Python image instead, which ships
    # Chromium and all its correct OS-matched dependencies already installed -
    # sidesteps the mismatch entirely rather than hand-patching package names.
    builder = (
        Template()
        .from_image("mcr.microsoft.com/playwright/python:v1.49.0-noble")
        .pip_install([
            "python-dotenv==1.0.1",
            "openai==1.57.0",
            "playwright==1.49.0",
            "Pillow==11.0.0",
            "claude-agent-sdk==0.2.134",
            "requests==2.32.3",
        ])
        .run_cmd("playwright install chromium")
        # FINDING (2026-08-10), the REAL root cause of the "Executable
        # doesn't exist at /home/user/.cache/ms-playwright/..." error -
        # confirmed by direct filesystem inspection, not guessed: the
        # browsers genuinely exist at /ms-playwright/... (both the base
        # image's own copy and the reinstall above agree on this path).
        # Microsoft's own Dockerfile almost certainly sets
        # PLAYWRIGHT_BROWSERS_PATH=/ms-playwright, but E2B's template
        # system does not carry a base image's Docker ENV instructions
        # through to the running sandbox (confirmed empty via `env | grep
        # -i playwright` at runtime) - so Playwright's Python client falls
        # back to its default per-user cache path, which is empty. Setting
        # this explicitly on the template is the actual fix.
        .set_envs({"PLAYWRIGHT_BROWSERS_PATH": "/ms-playwright"})
    )

    def log(entry):
        safe_message = entry.message.encode("ascii", errors="replace").decode("ascii")
        print(f"  [{entry.level}] {safe_message}")

    print(f"Building template '{TEMPLATE_ALIAS}' (default size: 2 vCPU, 1024MB)...")
    print("This installs Python packages + Chromium once, at build time - expect a few minutes.\n")

    build_info = Template.build(
        builder,
        name=TEMPLATE_ALIAS,
        alias=TEMPLATE_ALIAS,
        cpu_count=2,
        memory_mb=1024,
        on_build_logs=log,
        api_key=os.environ["E2B_API_KEY"],
    )
    print(f"\nBuild complete: {build_info}")
    print(f"\nUse this template in Sandbox.create(template='{TEMPLATE_ALIAS}')")


if __name__ == "__main__":
    main()
