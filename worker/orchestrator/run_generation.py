"""
Step D: the real orchestrator. Wires together everything verified in Steps
A-C into one actual run - the first time the agent has ever executed
anywhere.

Sequence:
  1. Insert a `runs` row (queued) - a run's existence is durable from the
     start, not just its eventual output.
  2. Hydrate (worker/hydration/generation.py - already proven in isolation).
  3. Mint signed upload URLs (worker/orchestrator/upload_urls.py - already
     proven in isolation).
  4. Create an anonymous E2B sandbox from the cq-generation-v1 custom
     template (worker/sandbox_images/generation/build_template.py) - a
     one-time, human-run build step with dependencies + Chromium
     pre-installed, built after the original "install everything at
     runtime" approach hit a real memory ceiling on E2B's default 1GB
     sandbox. Building this template does not violate the "clean box"
     disqualifier - see the reasoning recorded in build_template.py and
     DECISIONS.md.
  5. Write hydrated files + agent_runner.py into the sandbox (no
     requirements.txt/dependency install needed anymore - already baked
     into the template).
  6. Execute agent_runner.py inside the sandbox, with ONLY
     ANTHROPIC_API_KEY, OPENAI_API_KEY, and PLAYWRIGHT_BROWSERS_PATH as env
     vars - no Supabase key, no E2B key, no Kernel/Adstream creds anywhere
     near this box.
  7. Destroy the sandbox.
  8. Verify success by reading Storage back - never by reading the
     sandbox's filesystem (already destroyed by this point anyway).
  9. Update the `runs` row to succeeded/failed accordingly.
"""
import os
import sys
import threading
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
from e2b import Sandbox

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(ROOT, ".env"))

sys.path.insert(0, os.path.join(ROOT, "supabase"))
sys.path.insert(0, os.path.join(ROOT, "worker", "hydration"))
sys.path.insert(0, os.path.join(ROOT, "worker", "hydration", ".venv", "Lib", "site-packages"))

from onboarding import get_client  # noqa: E402
from generation import hydrate_generation  # noqa: E402
from upload_urls import mint_upload_urls  # noqa: E402

AGENT_DIR = os.path.join(ROOT, "worker", "sandbox_images", "generation")
SANDBOX_TIMEOUT_S = 900  # 15 min ceiling for this first real run


def run_generation(tenant_id, request_id, revision_number):
    client = get_client()

    print("1. Recording the run's existence before anything else happens...")
    run = client.table("runs").insert({
        "type": "generate",
        "tenant_id": tenant_id,
        "request_id": request_id,
        "status": "queued",
    }).execute().data[0]
    run_id = run["id"]
    print(f"   run_id: {run_id}")

    try:
        started_at = datetime.now(timezone.utc).isoformat()
        client.table("runs").update({"status": "running", "started_at": started_at}).eq("id", run_id).execute()

        print("\n2. Hydrating (skill + this tenant's real brand kit + this job's copy)...")
        files = hydrate_generation(tenant_id, request_id, revision_number)
        print(f"   {len(files)} files")

        print("\n3. Minting signed upload URLs, one per expected output file...")
        upload_urls = mint_upload_urls(tenant_id, request_id, revision_number)
        print(f"   {len(upload_urls)} URLs minted")
        import json
        files["job/upload_urls.json"] = json.dumps(upload_urls).encode("utf-8")

        print("\n4. Creating an anonymous E2B sandbox from the cq-generation-v1 template")
        print("   (no tenant/task metadata; deps + Chromium already baked in - see")
        print("   worker/sandbox_images/generation/build_template.py)...")
        sbx = Sandbox.create(template="cq-generation-v1", timeout=SANDBOX_TIMEOUT_S)
        print(f"   sandbox_id: {sbx.sandbox_id}")
        client.table("runs").update({"sandbox_id": sbx.sandbox_id}).eq("id", run_id).execute()

        try:
            print("\n5. Writing hydrated files + agent_runner.py into the sandbox...")
            # Per-file progress + a bounded per-write timeout on purpose - a
            # silent multi-minute loop with no output is indistinguishable
            # from a genuine hang from the outside. A write that's actually
            # stuck now fails loudly within 30s instead of hanging forever.
            all_files = dict(files)
            with open(os.path.join(AGENT_DIR, "agent_runner.py"), "rb") as f:
                all_files["agent_runner.py"] = f.read()
            for i, (rel_path, data) in enumerate(all_files.items(), 1):
                print(f"   [{i}/{len(all_files)}] writing {rel_path} ({len(data)} bytes)...")
                sbx.files.write(rel_path, data, request_timeout=30)
            print(f"   wrote {len(all_files)} files total (no requirements.txt install needed - "
                  f"dependencies are already in the template)")

            print("\n6. Executing agent_runner.py INSIDE the sandbox...")
            print("   (this is the actual agent run - real Anthropic + OpenAI spend starts now)")
            anthropic_key = os.environ["ANTHROPIC_API_KEY"]
            openai_key = os.environ["OPENAI_API_KEY"]

            # Run in the background and wait from a separate thread, so the
            # main thread is free to poll sbx.get_metrics() concurrently -
            # independent, orchestrator-side telemetry about the box's own
            # CPU/memory, not anything read from the agent's work. This is
            # what would have shown the original memory-ceiling problem
            # directly instead of us inferring it from a vague error.
            handle = sbx.commands.run(
                "python agent_runner.py .",
                background=True,
                envs={
                    "ANTHROPIC_API_KEY": anthropic_key,
                    "OPENAI_API_KEY": openai_key,
                    # FINDING (2026-08-10): the template's own env (set via
                    # set_envs at build time) does not persist into a
                    # running sandbox's environment - confirmed by direct
                    # inspection. Must be passed here, at actual command
                    # execution, where it correctly inherits down through
                    # agent_runner.py's own child processes (including the
                    # agent's own Bash tool calls to render_html.py).
                    "PLAYWRIGHT_BROWSERS_PATH": "/ms-playwright",
                },
                timeout=SANDBOX_TIMEOUT_S - 60,
            )

            wait_outcome = {}

            def _wait_for_agent():
                try:
                    wait_outcome["result"] = handle.wait(
                        on_stdout=lambda s: print(f"   [sandbox] {s}", end=""),
                        on_stderr=lambda s: print(f"   [sandbox:err] {s}", end=""),
                    )
                except Exception as e:  # noqa: BLE001 - re-surfaced in the main thread below
                    wait_outcome["error"] = e

            wait_thread = threading.Thread(target=_wait_for_agent, daemon=True)
            wait_thread.start()

            while wait_thread.is_alive():
                wait_thread.join(timeout=15)
                if wait_thread.is_alive():
                    try:
                        metrics = sbx.get_metrics()
                        if metrics:
                            m = metrics[-1]
                            mem_pct = (m.mem_used / m.mem_total * 100) if m.mem_total else 0
                            print(f"   [metrics] cpu={m.cpu_used_pct:.0f}%  "
                                  f"mem={m.mem_used / 1e6:.0f}MB/{m.mem_total / 1e6:.0f}MB ({mem_pct:.0f}%)")
                    except Exception as e:
                        print(f"   [metrics] fetch failed: {e}")

            if "error" in wait_outcome:
                err = wait_outcome["error"]
                # CommandExitException IS-A CommandResult (multiple
                # inheritance, confirmed by reading the SDK source directly
                # rather than assuming) - it carries exit_code/stdout/stderr
                # itself, there's no separate .result to unwrap.
                if hasattr(err, "exit_code"):
                    agent_result = err
                    print(f"\n   agent process exited non-zero (exit code {agent_result.exit_code})")
                else:
                    raise err
            else:
                agent_result = wait_outcome["result"]
                print(f"\n   agent process exit code: {agent_result.exit_code}")

        finally:
            print(f"\n7. Destroying sandbox {sbx.sandbox_id}...")
            sbx.kill()
            print("   destroyed")

        print("\n8. Verifying success by reading Storage back - NOT the (now-destroyed) sandbox...")
        tenant = client.table("tenants").select("*").eq("id", tenant_id).single().execute().data
        result_path = f"{request_id}/revisions/{revision_number}/RESULT.json"
        try:
            result_bytes = client.storage.from_(tenant["jobs_bucket"]).download(result_path)
            print(f"   RESULT.json found in Storage ({len(result_bytes)} bytes) - run produced real output")
            status = "succeeded" if agent_result.exit_code == 0 else "failed"
        except Exception as e:
            print(f"   RESULT.json NOT found in Storage: {e}")
            status = "failed"

        ended_at = datetime.now(timezone.utc).isoformat()
        client.table("runs").update({"status": status, "ended_at": ended_at}).eq("id", run_id).execute()
        print(f"\nRun {run_id} marked '{status}'.")
        return run_id, status

    except Exception as e:
        ended_at = datetime.now(timezone.utc).isoformat()
        client.table("runs").update({
            "status": "failed", "error_message": str(e)[:2000], "ended_at": ended_at,
        }).eq("id", run_id).execute()
        print(f"\nRun {run_id} FAILED: {e}")
        raise


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python run_generation.py <tenant_id> <request_id> <revision_number>")
        sys.exit(1)
    run_generation(sys.argv[1], sys.argv[2], int(sys.argv[3]))
