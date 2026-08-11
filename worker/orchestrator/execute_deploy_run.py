"""
Phase 4: executes an already-claimed deploy run. Same shape as
execute_run.py (hydrate -> mint signed URLs -> sandbox -> run agent ->
destroy -> verify via Storage only -> update DB), deliberately a SEPARATE
file rather than a modification of execute_run.py - the brief's own
instruction is that a deploy should reuse the shape, not the file, and the
tested/working generate+edit path stays untouched by this addition.

Assumes the run is ALREADY 'running' with started_at set - same contract as
execute_run.py, satisfied atomically by claim_next_run() before this is ever
called.
"""
import json
import os
import sys
import threading
from datetime import datetime, timezone

from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(ROOT, ".env"))

sys.path.insert(0, os.path.join(ROOT, "supabase"))
sys.path.insert(0, os.path.join(ROOT, "worker", "hydration"))
sys.path.insert(0, os.path.join(ROOT, "worker", "hydration", ".venv", "Lib", "site-packages"))

from onboarding import get_client  # noqa: E402
from deployment import hydrate_deploy  # noqa: E402
from storage_paths import revision_prefix  # noqa: E402
from upload_urls import mint_deploy_upload_urls  # noqa: E402

AGENT_DIR = os.path.join(ROOT, "worker", "sandbox_images", "deployment")
SANDBOX_TIMEOUT_S = 900


def execute_claimed_deploy_run(run):
    client = get_client()
    run_id = run["id"]
    tenant_id = run["tenant_id"]
    request_id = run["request_id"]
    revision_number = run["revision_number"]
    reason = run.get("reason") or "initial"

    def log(msg):
        print(f"[deploy run {run_id}] {msg}")

    # Same discipline as execute_run.py's own FINDING (2026-08-11): keep the
    # e2b import AND every DB/Storage lookup inside the try block, so any
    # failure here - including one before a revision_id is even known - is
    # recorded as this run's failure, never silently dropped past
    # dispatcher.py's own except (which assumes this file already recorded
    # it).
    revision_id = None
    try:
        from sandbox_factory import create_sandbox

        tenant = client.table("tenants").select("*").eq("id", tenant_id).single().execute().data
        request = client.table("requests").select("*").eq("id", request_id).single().execute().data
        prefix = revision_prefix(request["campaign"], request_id, revision_number)

        revision = (
            client.table("revisions")
            .select("id")
            .eq("request_id", request_id)
            .eq("revision_number", revision_number)
            .single()
            .execute()
            .data
        )
        revision_id = revision["id"]

        try:
            started_at = run.get("started_at") or datetime.now(timezone.utc).isoformat()
            attempt_ts = started_at.replace(":", "-").split(".")[0]
            run_short = run_id.split("-")[0]
            attempt_path = f"{prefix}/deploy/attempts/{attempt_ts}-{run_short}-{reason}.json"
            client.storage.from_(tenant["jobs_bucket"]).upload(
                attempt_path,
                json.dumps({
                    "run_id": run_id, "type": run.get("type"), "reason": reason,
                    "started_at": started_at,
                }, indent=2).encode("utf-8"),
                {"upsert": "true"},
            )
            log(f"attempt logged: {attempt_path}")
        except Exception as e:  # noqa: BLE001 - audit trail, never worth failing the run over
            log(f"attempt log write failed (non-fatal): {e}")

        log("hydrating (this revision's final creative only - no brand-kit, no OpenAI key)...")
        files = hydrate_deploy(tenant_id, request_id, revision_number)
        log(f"{len(files)} files")

        log("minting signed upload URLs for deploy outputs (recording.webm, RESULT.json, ...)...")
        upload_urls = mint_deploy_upload_urls(tenant_id, request_id, revision_number)
        files["job/upload_urls.json"] = json.dumps(upload_urls).encode("utf-8")

        log("creating an anonymous E2B sandbox from the cq-deployment-v1 template...")
        sbx = create_sandbox(template="cq-deployment-v1", timeout=SANDBOX_TIMEOUT_S)
        log(f"sandbox_id: {sbx.sandbox_id}")
        client.table("runs").update({"sandbox_id": sbx.sandbox_id}).eq("id", run_id).execute()

        try:
            log("writing hydrated files + deploy_agent_runner.py into the sandbox...")
            all_files = dict(files)
            with open(os.path.join(AGENT_DIR, "deploy_agent_runner.py"), "rb") as f:
                all_files["deploy_agent_runner.py"] = f.read()
            for rel_path, data in all_files.items():
                for attempt in range(3):
                    try:
                        sbx.files.write(rel_path, data, request_timeout=30)
                        break
                    except Exception as e:  # noqa: BLE001 - narrowed by re-raising on the last attempt
                        if attempt == 2:
                            raise
                        log(f"  write of {rel_path} failed (attempt {attempt + 1}/3): {e} - retrying...")
            log(f"wrote {len(all_files)} files total")

            log("executing deploy_agent_runner.py INSIDE the sandbox "
                "(real Anthropic spend + a real Adstream deploy starts now)...")
            anthropic_key = os.environ["ANTHROPIC_API_KEY"]
            adstream_login_url = os.environ.get("ADSTREAM_LOGIN_URL", "")
            adstream_email = os.environ.get("ADSTREAM_EMAIL", "")
            adstream_password = os.environ.get("ADSTREAM_PASSWORD", "")

            handle = sbx.commands.run(
                "python deploy_agent_runner.py .",
                background=True,
                envs={
                    "ANTHROPIC_API_KEY": anthropic_key,
                    "ADSTREAM_LOGIN_URL": adstream_login_url,
                    "ADSTREAM_EMAIL": adstream_email,
                    "ADSTREAM_PASSWORD": adstream_password,
                    "PLAYWRIGHT_BROWSERS_PATH": "/ms-playwright",
                    # Deliberately absent: OPENAI_API_KEY. This agent
                    # never generates anything - DECISIONS.md SS4.4.
                },
                timeout=SANDBOX_TIMEOUT_S - 60,
            )

            wait_outcome = {}

            def _wait_for_agent():
                try:
                    wait_outcome["result"] = handle.wait(
                        on_stdout=lambda s: log(f"[sandbox] {s.rstrip()}"),
                        on_stderr=lambda s: log(f"[sandbox:err] {s.rstrip()}"),
                    )
                except Exception as e:  # noqa: BLE001 - re-surfaced below
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
                            log(f"[metrics] cpu={m.cpu_used_pct:.0f}%  "
                                f"mem={m.mem_used / 1e6:.0f}MB/{m.mem_total / 1e6:.0f}MB ({mem_pct:.0f}%)")
                    except Exception as e:
                        log(f"[metrics] fetch failed: {e}")

            if "error" in wait_outcome:
                err = wait_outcome["error"]
                if hasattr(err, "exit_code"):
                    agent_result = err
                    log(f"agent process exited non-zero (exit code {agent_result.exit_code})")
                else:
                    raise err
            else:
                agent_result = wait_outcome["result"]
                log(f"agent process exit code: {agent_result.exit_code}")

        finally:
            log(f"destroying sandbox {sbx.sandbox_id}...")
            sbx.kill()
            log("destroyed")

        # "No recording, no deploy" (the brief's own words) - this check is
        # the structural enforcement of that rule, not a suggestion left to
        # the agent's own honesty. A missing recording fails the run
        # regardless of what RESULT.json claims or what the exit code was.
        log("verifying success by reading Storage back - NOT the (now-destroyed) sandbox...")
        recording_path = f"{prefix}/deploy/recording.webm"
        result_path = f"{prefix}/deploy/RESULT.json"
        recording_ok = False
        try:
            recording_bytes = client.storage.from_(tenant["jobs_bucket"]).download(recording_path)
            recording_ok = len(recording_bytes) > 0
            log(f"recording.webm found in Storage ({len(recording_bytes)} bytes)")
        except Exception as e:
            log(f"recording.webm NOT found in Storage: {e} - this alone fails the run")

        deploy_result = None
        try:
            result_bytes = client.storage.from_(tenant["jobs_bucket"]).download(result_path)
            deploy_result = json.loads(result_bytes.decode("utf-8"))
            log(f"RESULT.json found in Storage: {deploy_result}")
        except Exception as e:
            log(f"RESULT.json NOT found in Storage: {e}")

        status = (
            "succeeded"
            if recording_ok and agent_result.exit_code == 0 and deploy_result and deploy_result.get("status") == "completed"
            else "failed"
        )

        ended_at = datetime.now(timezone.utc).isoformat()
        run_update = {"status": status, "ended_at": ended_at}
        if status == "succeeded":
            run_update["revision_id"] = revision_id

        client.table("deploys").insert({
            "revision_id": revision_id,
            "run_id": run_id,
            "adstream_ad_name": (deploy_result or {}).get("adstream_ad_name"),
            "adstream_url": (deploy_result or {}).get("adstream_url"),
            # verified is only ever true if BOTH the agent's own RESULT.json
            # claims it AND the recording that proves the session happened
            # actually exists in Storage - the agent's word alone is never
            # sufficient, same posture as generation's Storage-verified
            # success check.
            "verified": bool(recording_ok and (deploy_result or {}).get("verified")),
            "recording_path": recording_path if recording_ok else None,
            "status": status,
        }).execute()

        client.table("runs").update(run_update).eq("id", run_id).execute()
        log(f"marked '{status}'.")
        return run_id, status

    except Exception as e:
        ended_at = datetime.now(timezone.utc).isoformat()
        client.table("runs").update({
            "status": "failed", "error_message": str(e)[:2000], "ended_at": ended_at,
        }).eq("id", run_id).execute()
        if revision_id:
            # A failed deploy never changes the revision's own status - the
            # generated asset is still exactly as good as it was; only the
            # deploy attempt failed. (Unlike a failed generation/edit, which
            # DOES fail its revision, because there the revision itself is
            # what didn't get produced.)
            pass
        log(f"FAILED: {e}")
        raise


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python execute_deploy_run.py <run_id>  (run must already be 'running')")
        sys.exit(1)
    client = get_client()
    run = client.table("runs").select("*").eq("id", sys.argv[1]).single().execute().data
    execute_claimed_deploy_run(run)
