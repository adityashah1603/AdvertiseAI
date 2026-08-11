"""
Builds the reusable E2B template for deployment sandboxes: a Python base
image with Playwright + Chromium pre-installed, same shape as
worker/sandbox_images/generation/build_template.py.

Deliberately a SEPARATE template/image from generation's, not a shared one -
per ROADMAP.md's locked decision: "They need disjoint tools and disjoint
credentials; one fat image widens each run's blast radius for no benefit."
This image never installs `openai` (the deployment agent never gets that
key - see DECISIONS.md SS4.4) and generation's image never installs
anything Adstream-specific.

One-time (or rare, when deps change) setup step, run by a human - not
something the orchestrator runs per request. Same rule-check as
generation's template: pre-baking runtime dependencies does not violate the
"clean box" disqualifier - this template is identical for every tenant/task,
zero tenant/task identity baked in, only software.

Usage:
    python build_template.py
"""
import os
import sys

from dotenv import load_dotenv
from e2b import Template

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
load_dotenv(os.path.join(ROOT, ".env"))

TEMPLATE_ALIAS = "cq-deployment-v1"


def main():
    # Same base image + PLAYWRIGHT_BROWSERS_PATH fix already proven working
    # for the generation template (worker/sandbox_images/generation/
    # build_template.py) - both findings apply identically here, there's no
    # reason to re-discover them: Microsoft's own Playwright+Python image
    # ships Chromium with correctly matched OS deps (a bare python:3.11 +
    # `playwright install chromium --with-deps` fails on this Debian
    # "trixie" base), and E2B's template system doesn't carry a base
    # image's own Docker ENV instructions through to the running sandbox,
    # so PLAYWRIGHT_BROWSERS_PATH has to be set explicitly.
    builder = (
        Template()
        .from_image("mcr.microsoft.com/playwright/python:v1.49.0-noble")
        .pip_install([
            "python-dotenv==1.0.1",
            "playwright==1.49.0",
            "claude-agent-sdk==0.2.134",
            "requests==2.32.3",
        ])
        .run_cmd("playwright install chromium")
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
    print(f"\nUse this template via create_sandbox(template='{TEMPLATE_ALIAS}') "
          "(worker/orchestrator/sandbox_factory.py)")


if __name__ == "__main__":
    main()
