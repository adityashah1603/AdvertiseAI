"""
deploy_agent_runner.py - Phase 4's autonomous in-sandbox agent, the same
shape as worker/sandbox_images/generation/agent_runner.py: the Claude Agent
SDK drives a real browser (Playwright, inside THIS sandbox - never the
orchestrator's machine, per the brief's explicit "the browser runs where
the agent runs" requirement) through Adstream's create/publish flow, then
saves its own output before the box dies.

Self-contained on purpose - does not import anything from
worker/sandbox_images/generation/. The two sandbox images stay genuinely
disjoint (ROADMAP.md's locked decision), so a small duplicated
upload_output_file tool here is the right call, not a shared module that
would couple the two images together.

Expects to run with its working directory set to the root of a hydrated
file tree (see worker/hydration/deployment.py +
worker/orchestrator/upload_urls.py):
  job/request.json              - campaign, copy, canvas list
  job/creative/<name>.png       - this revision's final rendered PNGs,
                                   the only "creative" this agent ever sees
  job/upload_urls.json          - {relative_output_path: signed_upload_url},
                                   minted by the orchestrator BEFORE this
                                   sandbox existed - this sandbox never sees
                                   the service-role key, only these narrow,
                                   single-path, single-operation,
                                   time-limited tokens.

Credentials this process receives via env (set by execute_deploy_run.py,
never baked into the template): ANTHROPIC_API_KEY, ADSTREAM_LOGIN_URL,
ADSTREAM_EMAIL, ADSTREAM_PASSWORD. Never OPENAI_API_KEY, never a brand-kit
credential - this agent has nothing to design, only to upload and publish
what already exists (DECISIONS.md SS4.4).
"""
import asyncio
import json
import mimetypes
import os
import sys
from pathlib import Path

import requests
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    create_sdk_mcp_server,
    query,
    tool,
)


def load_context(root: Path):
    job = json.loads((root / "job" / "request.json").read_text(encoding="utf-8"))
    upload_urls = json.loads((root / "job" / "upload_urls.json").read_text(encoding="utf-8"))
    return job, upload_urls


def _upload_via_signed_url(url: str, local_path: Path) -> tuple[bool, str]:
    """Identical mechanics to agent_runner.py's own uploader - verified for
    real in Step A (worker/hydration/test_signed_upload.py): multipart
    form-data PUT to a signed URL, no other credential needed."""
    if not local_path.exists():
        return False, f"local file does not exist: {local_path}"
    content_type = mimetypes.guess_type(str(local_path))[0] or "application/octet-stream"
    with open(local_path, "rb") as f:
        resp = requests.put(url, files={"file": (local_path.name, f, content_type)})
    if resp.status_code not in (200, 201):
        return False, f"HTTP {resp.status_code}: {resp.text[:300]}"
    return True, f"uploaded {local_path.name} ({local_path.stat().st_size} bytes)"


def make_uploader_tool(root: Path, upload_urls: dict):
    @tool(
        "upload_output_file",
        "Upload a local output file to its designated storage location. Call this "
        "immediately after you finish writing each output file (recording.webm, "
        "then RESULT.json last). output_key must exactly match one of the known "
        "keys - if you're unsure what keys exist, the error message will list them. "
        "A failure here means the file is NOT saved - read the error and retry, "
        "don't move on silently.",
        {"local_path": str, "output_key": str},
    )
    async def upload_output_file(args):
        local_path = root / "output" / args["local_path"]
        output_key = args["output_key"]

        if output_key not in upload_urls:
            known = ", ".join(sorted(upload_urls.keys()))
            return {
                "content": [{"type": "text", "text": f"No signed URL for '{output_key}'. Known keys: {known}"}],
                "is_error": True,
            }

        ok, message = _upload_via_signed_url(upload_urls[output_key], local_path)
        return {"content": [{"type": "text", "text": message}], "is_error": not ok}

    return upload_output_file


def build_system_prompt() -> str:
    login_url = os.environ.get("ADSTREAM_LOGIN_URL", "").strip()
    email = os.environ.get("ADSTREAM_EMAIL", "").strip()

    return f"""You are the CharacterQuilt deployment agent, running autonomously inside a
disposable sandbox with no human available to answer questions - make every
call yourself and record your reasoning as you go.

Your job: take an already-finished, already-approved ad creative and publish
it into Adstream (a stand-in ads manager), using a real browser you drive
yourself with Playwright. You do not design anything - the creative in
job/creative/ is final. Your only tasks are: sign in, create the ad, upload
the creative, publish it, and then prove it actually worked by reading the
ad's own detail page back - not by trusting a toast message or your own
memory of clicking "Publish."

Your working directory already contains:
  job/request.json        - campaign name and copy (for the ad name /
                             destination URL - see below for what to do if
                             a field is blank)
  job/creative/*.png       - the final rendered creative(s) to upload,
                             one file per canvas size

Adstream:
  URL:   {login_url or '(ADSTREAM_LOGIN_URL not set)'}
  Email: {email or '(ADSTREAM_EMAIL not set)'}
  Password: read from the ADSTREAM_PASSWORD environment variable yourself
            (`echo $ADSTREAM_PASSWORD` via Bash) - it is not printed here on
            purpose, so it never ends up verbatim in your own transcript.

Adstream is a real, imperfect web app, not a mock that behaves conveniently.
Known quirks, confirmed real, that you MUST account for - do not assume
timing, always observe and wait for the actual page state:
  - Ad names are NORMALIZED on save. What you typed is not necessarily what
    gets stored - after saving, read the name back from the page itself and
    use THAT as the ad name in RESULT.json, never the string you typed.
  - "Next" and "Publish" buttons stay DISABLED until every required field on
    that step is filled in. If a click does nothing, that's very likely why
    - inspect the page (a screenshot, or reading button attributes) before
    assuming something is broken.
  - Publishing takes 2-9 seconds. Poll/wait for the actual resulting state
    (a URL change, a status field, the detail page loading) - do not use a
    fixed short sleep and assume it's done.
  - Duplicate ad names are allowed - Adstream does not deduplicate. Never
    rely on name uniqueness to find or verify "your" ad; use the URL/id
    Adstream gives you after creation.
  - The success toast lasts 6 seconds and does NOT clear on navigation, so
    it can still be visible on a page it has nothing to do with. A visible
    toast proves NOTHING about the ad you actually care about - the ad
    detail page is the only source of truth, always read it fresh after
    navigating there.

Non-negotiable order of operations:
  1. Start screen recording BEFORE opening Adstream at all - see the
     "Recording" section below. A run that ends without a real recording
     uploaded is a FAILED run, full stop, regardless of what the browser
     did on screen. This is the brief's own rule, not a suggestion.
  2. Sign in, complete the create flow, upload the creative (use the
     job/creative/*.png file(s) directly), publish.
  3. Navigate to the ad's own detail page. Read back, from that page:
     the ad name as actually stored (post-normalization) and its publish
     status. This read-back is what "verified" means - you may not set
     verified: true in RESULT.json without having actually done this and
     seen a real published state on the real detail page.
  4. Close the browser context (this finalizes the recording file - see
     below), save the recording + RESULT.json to ./output/, upload both via
     the upload_output_file tool, recording FIRST, RESULT.json LAST (if a
     later step fails, you want the recording of what actually happened
     already saved).

Recording, concretely - Playwright's own video capture, no external
service. This exact pattern, adapted as needed:

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            record_video_dir="output/_video",
            viewport={{"width": 1280, "height": 800}},
        )
        page = context.new_page()
        # ... everything you do happens through `page` from here ...
        context.close()  # REQUIRED before the video file is finalized/readable
        recorded_path = page.video.path()  # only valid after context.close()
        # copy/rename recorded_path to output/recording.webm, then upload
        # it with output_key="recording.webm" - it will NOT be named that
        # by Playwright itself, Playwright picks its own filename.

If the destination URL in job/request.json's copy.cta_href is blank, do not
block on it - use a reasonable placeholder (e.g. the campaign name turned
into a URL-safe slug under https://example.com/) and note in RESULT.json
that the real destination was not provided by the request. The same applies
to a blank ad name: fall back to the campaign name. Never invent a
destination that looks like a real customer domain.

Write ./output/RESULT.json when done, with at least: {{"status":
"completed"|"failed", "adstream_ad_name": <name as read from the detail
page>, "adstream_url": <the detail page URL>, "verified": true|false, "notes":
<anything you could not do and why>}}. verified must be true only if you
actually completed the step-3 read-back above. Never claim publication
without it.
"""


def build_task_prompt(job: dict) -> str:
    creative_names = ", ".join(f"job/creative/{c['name']}.png" for c in job["canvases"])
    return f"""Deploy this ad to Adstream.

Campaign: {job['campaign']}
Copy (for the ad name / destination URL - see your system prompt for what to
do if a field below is blank):
{json.dumps(job['copy'], indent=2)}

Creative file(s) to upload: {creative_names}

Follow the order of operations in your system prompt exactly: start
recording first, sign in, create, upload, publish, read the detail page
back, then save and upload the recording and RESULT.json.
"""


def _message_to_dict(message):
    if hasattr(message, "__dict__"):
        return {"type": type(message).__name__, **message.__dict__}
    return {"type": type(message).__name__, "value": str(message)}


def _write_transcript(root: Path, transcript: list) -> Path:
    transcript_path = root / "output" / "agent-transcript.jsonl"
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    with open(transcript_path, "w", encoding="utf-8") as f:
        for message in transcript:
            f.write(json.dumps(_message_to_dict(message), default=str) + "\n")
    return transcript_path


def _write_status(root: Path, turn_count: int, last_action: str) -> Path:
    import datetime

    status_path = root / "output" / "_status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status = {
        "last_activity_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "turn_count": turn_count,
        "last_action": last_action,
    }
    status_path.write_text(json.dumps(status), encoding="utf-8")
    return status_path


async def run(root: Path):
    job, upload_urls = load_context(root)
    uploader = make_uploader_tool(root, upload_urls)
    uploader_server = create_sdk_mcp_server(name="uploader", tools=[uploader])

    options = ClaudeAgentOptions(
        system_prompt=build_system_prompt(),
        cwd=str(root),
        tools=["Bash", "Read", "Write", "Glob", "mcp__uploader__upload_output_file"],
        mcp_servers={"uploader": uploader_server},
        permission_mode="bypassPermissions",  # no human present to approve tool calls
        model="claude-sonnet-5",
        max_turns=80,  # exploratory browser-state waiting needs more headroom than generation's fixed pipeline
        max_budget_usd=5.0,  # safety cap - a runaway loop shouldn't be a silent surprise bill
        # Same finding as generation's agent_runner.py: the SDK's subprocess
        # IPC channel defaults to a 1MB max message size, which a
        # base64-encoded screenshot can exceed. Raised for the same reason -
        # this agent needs to actually look at real screenshots to know
        # whether a button is enabled or a page finished loading.
        max_buffer_size=50 * 1024 * 1024,
    )

    transcript = []
    result = None
    turn_count = 0
    TRANSCRIPT_CHECKPOINT_EVERY = 5

    async for message in query(prompt=build_task_prompt(job), options=options):
        transcript.append(message)
        turn_count += 1
        last_action = f"{type(message).__name__}"

        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    print(f"[agent] {block.text}")
                    last_action = f"text: {block.text[:100]}"
                elif isinstance(block, ToolUseBlock):
                    print(f"[tool call] {block.name} {json.dumps(block.input)[:200]}")
                    last_action = f"tool call: {block.name}"
        elif isinstance(message, ResultMessage):
            result = message

        status_path = _write_status(root, turn_count, last_action)
        if "_status.json" in upload_urls:
            _upload_via_signed_url(upload_urls["_status.json"], status_path)  # best-effort, not worth failing the run over

        if turn_count % TRANSCRIPT_CHECKPOINT_EVERY == 0 and "agent-transcript.jsonl" in upload_urls:
            checkpoint_path = _write_transcript(root, transcript)
            ok, msg = _upload_via_signed_url(upload_urls["agent-transcript.jsonl"], checkpoint_path)
            print(f"[transcript checkpoint @ turn {turn_count}] {'OK' if ok else 'FAILED'}: {msg}")

    transcript_path = _write_transcript(root, transcript)
    if "agent-transcript.jsonl" in upload_urls:
        ok, msg = _upload_via_signed_url(upload_urls["agent-transcript.jsonl"], transcript_path)
        print(f"[transcript upload] {'OK' if ok else 'FAILED'}: {msg}")

    if result is None:
        print("FAILED: no ResultMessage received - the agent session ended abnormally.", file=sys.stderr)
        sys.exit(1)
    if result.is_error:
        print(f"FAILED: {result.result}", file=sys.stderr)
        sys.exit(1)

    print(f"\nDone. {result.num_turns} turns, ${result.total_cost_usd:.4f}, stop_reason={result.stop_reason}")


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    asyncio.run(run(root))
