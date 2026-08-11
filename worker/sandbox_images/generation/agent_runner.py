"""
agent_runner.py - the autonomous version of what I (the outer Claude Code
session) did by hand in Phase 0: read the brand, generate a plate, build
the HTML overlay, render it, look at it, save it. Same job, no human
steering it turn by turn.

Deliberately minimal custom tooling, with one exception. The Claude Agent
SDK gives the agent Bash/Read/Write/Glob for free - it's literally Claude
Code as a library, and its Read tool is already multimodal (can view a PNG
it just rendered), which is exactly what SKILL.md's "look at it" step
needs. So for plate generation and rendering, the agent just calls the two
CLI scripts already proven in Phase 0 (tools/call_gpt_image.py,
tools/render_html.py) via Bash, exactly like I did by hand.

The ONE exception is saving output. That's deliberately a real custom tool
(upload_output_file, an in-process MCP tool per the SDK's create_sdk_mcp_server)
rather than a hand-typed curl command, because the brief requires save
failures to be loud and actionable "in the same run" - an LLM-improvised
curl call that's subtly wrong (bad multipart flag, wrong content-type)
would fail silently from the agent's own perspective. This tool's HTTP
mechanics are the exact ones verified for real in Step A
(worker/hydration/test_signed_upload.py): a signed URL's token alone is
sufficient, no other credential, multipart form-data, not a raw PUT body.

Tool availability is restricted via `tools=[...]` (the base set), not
`allowed_tools` - allowed_tools only controls auto-approval within a
permission_mode that still prompts, which is moot once permission_mode is
"bypassPermissions" (required here since no human is present inside a
sandbox to approve anything). The custom tool's SDK-assigned name is
"mcp__uploader__upload_output_file" - confirmed directly from the bundled
CLI's own naming pattern (mcp__${serverName}__${toolName}), not guessed.

Expects to run with its working directory set to the root of a hydrated
file tree (see worker/hydration/generation.py + worker/orchestrator/upload_urls.py):
  skill/SKILL.md
  skill/tools/call_gpt_image.py
  skill/tools/render_html.py
  brand_kit/DESIGN.md
  brand_kit/fonts/...
  brand_kit/brand/...
  job/request.json
  job/upload_urls.json          - {relative_output_path: signed_upload_url},
                                   minted by the orchestrator BEFORE this
                                   sandbox existed, using the trusted
                                   service-role key - this sandbox never
                                   sees that key, only these narrow,
                                   single-path, single-operation,
                                   time-limited tokens.
"""
import asyncio
import json
import mimetypes
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
    skill_md = (root / "skill" / "SKILL.md").read_text(encoding="utf-8")
    job = json.loads((root / "job" / "request.json").read_text(encoding="utf-8"))
    upload_urls = json.loads((root / "job" / "upload_urls.json").read_text(encoding="utf-8"))
    return skill_md, job, upload_urls


def _upload_via_signed_url(url: str, local_path: Path) -> tuple[bool, str]:
    """The verified-in-Step-A mechanics: multipart form-data PUT to a
    signed URL, no other credential. Returns (success, message)."""
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
        "immediately after you finish writing each output file (plate.png, "
        "overlay.html, render.png per canvas, and RESULT.json at the end). "
        "output_key must exactly match one of the known keys - if you're unsure "
        "what keys exist, the error message will list them. A failure here means "
        "the file is NOT saved - read the error and retry, don't move on silently.",
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


def build_system_prompt(skill_md: str) -> str:
    return f"""You are the CharacterQuilt design-generation agent, running autonomously
inside a disposable sandbox with no human available to answer questions -
make every call yourself and record your reasoning as you go.

Your working directory already contains everything you need:
  brand_kit/DESIGN.md           - the brand. Source of truth - nothing else
                                   you see (an inspiration file, a cached
                                   token export, your own prior assumption)
                                   may override it.
  brand_kit/fonts/*.ttf         - the brand's actual font files. Use these
                                   exact files, never a browser fallback.
  brand_kit/brand/*             - logo SVGs and an asset manifest.
  job/request.json              - this run's campaign, copy, and required
                                   canvas sizes.
  skill/tools/call_gpt_image.py - generates one plate PNG. Usage:
      python skill/tools/call_gpt_image.py --prompt-file <path> --width <W> --height <H> --out <path>
  skill/tools/render_html.py    - renders an HTML file to an exact-size PNG. Usage:
      python skill/tools/render_html.py --html <path> --width <W> --height <H> --out <path>

Run both of these via your Bash tool exactly as shown - they are already
built and proven, do not reimplement their logic.

Below is the full design-generation skill contract. Follow it exactly.

---
{skill_md}
---

CRITICAL, non-negotiable, learned from two real past failures:

1. Every font size you use MUST be exactly one of DESIGN.md's stated
   type-scale values (h1, h2, h3, body, caption) - for EVERY canvas size,
   not just the one that happens to have the most room. Do NOT scale a
   headline down to make it fit a short canvas, and do NOT scale it up
   just because a tall canvas has extra space. If a string does not fit at
   the correct size, solve it by repositioning, tightening line-height, or
   cutting the copy - never by picking a different font-size than
   DESIGN.md states. A previous run made exactly this mistake - shrinking
   headlines for landscape canvases and enlarging them for portrait ones -
   so treat this as a known trap, not a hypothetical one.

2. Each value has a fixed role - using a real DESIGN.md value in the WRONG
   role is still wrong, even though it isn't an invented number:
     - headline               -> h1
     - subhead / body copy    -> body
     - eyebrow                -> caption
     - h2/h3 are for actual subheadings within a layout, NOT a substitute
       for "body" when body feels too small. A later run made exactly
       this mistake - used h3 for subhead/CTA text instead of body,
       reasoning that 16px body "looked too small" against a large
       illustration. That reasoning is not a valid reason to pick a
       different named value. If body genuinely reads too small at actual
       size, that's a layout/composition problem to solve by adjusting the
       plate or spacing - not license to reach for a bigger named value.

Save every artifact for a canvas named <name> under ./output/<name>/:
  plate.png     - the raw generated plate
  overlay.html  - the HTML overlay (live text/logo, per the contract)
  render.png    - the final composited canvas, produced by render_html.py

Immediately after writing each of those files, call the upload_output_file
tool with local_path="<name>/plate.png" (etc.) and the matching output_key
(same relative path, e.g. "square/plate.png"). Do this per file, not once
at the end - if an upload fails partway through, you want to know which
specific file failed, not discover it after everything else already ran.

When every canvas is done, write ./output/RESULT.json summarizing what you
built, any brand-data inconsistencies you found and how you resolved them,
and anything you could not do and why - the same spirit as the findings
already logged in DECISIONS.md, but for this specific run. Upload it
too, with output_key="RESULT.json".

Some runs are EDITS to an ad that already exists, driven by human comments
left on the previous revision rather than a fresh brief. When that's the
case, the task prompt below will say so explicitly and point you at
job/prior_revision/<canvas>/{{plate.png,overlay.html,render.png}} (the
existing, already-approved-enough-to-comment-on output) and the actual
comments with their region coordinates. There is no rule anywhere that
decides for you whether a given comment needs a small overlay tweak (move
text, change a word, swap the CTA color) or a full plate regeneration
(the comment is about the photo/illustration itself, not the copy or
layout) - that judgment call is yours to make per comment, the same way a
human designer would read a comment and decide how much of the ad it
actually touches. Keep whatever a comment doesn't ask you to change
exactly as it was; re-deriving an ad from scratch when only one line of
copy needed to move defeats the point of an edit.
"""


def build_task_prompt(job: dict) -> str:
    canvases = "\n".join(f"  - {c['name']}: {c['width']}x{c['height']}" for c in job["canvases"])

    if job.get("is_edit"):
        comments = job.get("comments", [])
        comments_block = "\n\n".join(
            f"  Comment on canvas '{c['canvas_name']}', region "
            f"x={c['region'].get('x')} y={c['region'].get('y')} "
            f"w={c['region'].get('width')} h={c['region'].get('height')}:\n"
            f'  "{c["body"]}" - {c["author"] or "unknown"}'
            for c in comments
        ) or "  (no open comments - re-produce this revision as-is unless you spot a real brand violation)"

        return f"""Edit request - revision {job['revision_number']} of an ad that already
exists as revision {job['prior_revision_number']}.

Campaign: {job['campaign']}
Copy (current, may already reflect what the comments below are asking for -
check before assuming a comment is still unaddressed):
{json.dumps(job['copy'], indent=2)}

Canvases required:
{canvases}

The previous revision's actual output is available at
job/prior_revision/<canvas>/{{plate.png,overlay.html,render.png}} for each
canvas above - read it before changing anything.

Open comments left on the previous revision:
{comments_block}

For each canvas, decide whether the comments touching it call for a
targeted change (move/resize/recolor an overlay element, edit copy, swap
the CTA) or require a new plate (the comment is about the photo/
illustration itself). Produce ./output/<name>/{{plate.png,overlay.html,render.png}}
for every canvas exactly as a fresh generation would, following the skill
contract and the type-scale rules in your system prompt - reusing the
prior plate.png directly (copy it forward) is correct when no comment
requires regenerating it. Look at each final render before considering it
done, the same as any other run.
"""

    inspirations = job.get("inspirations") or []
    if inspirations:
        inspirations_block = "\n".join(f"  - job/inspirations/{f}" for f in inspirations) + (
            "\n\nOpen these with your Read tool if you want to look at them. Per your "
            "system prompt's skill contract: reference only - composition, rhythm, crop, "
            "how the brand behaves on a canvas. Never sample a color from one, never "
            "measure type off one, never copy its words, never extract or reuse any part "
            "of it as an asset. A file suffixed .MISSING.txt means that named inspiration "
            "could not be fetched - read the placeholder for why, then proceed without it."
        )
    else:
        inspirations_block = "  (none attached)"

    return f"""New generation request.

Campaign: {job['campaign']}
Copy:
{json.dumps(job['copy'], indent=2)}

Canvases required:
{canvases}

Inspirations attached:
{inspirations_block}

Generate a complete, on-brand ad for every canvas size listed above,
following the skill contract in your system prompt. Look at each render
before considering it done.
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
    skill_md, job, upload_urls = load_context(root)
    uploader = make_uploader_tool(root, upload_urls)
    uploader_server = create_sdk_mcp_server(name="uploader", tools=[uploader])

    options = ClaudeAgentOptions(
        system_prompt=build_system_prompt(skill_md),
        cwd=str(root),
        tools=["Bash", "Read", "Write", "Glob", "mcp__uploader__upload_output_file"],
        mcp_servers={"uploader": uploader_server},
        permission_mode="bypassPermissions",  # no human present to approve tool calls
        model="claude-sonnet-5",
        max_turns=60,
        max_budget_usd=5.0,  # safety cap - a runaway loop shouldn't be a silent surprise bill
        # FINDING (2026-08-11): the SDK's subprocess IPC channel defaults to
        # a 1,048,576-byte (1MB) max JSON message size - confirmed by
        # reading the SDK source directly (subprocess_cli.py's
        # _DEFAULT_MAX_BUFFER_SIZE), not guessed. A large rendered PNG
        # (base64-encoded, plus JSON framing overhead) read via the Read
        # tool can exceed that and kills the whole session with no
        # opportunity to recover - happened for real on a Duolingo landscape
        # plate. SKILL.md's "look at it" step requires the agent can
        # actually view full-resolution renders, so the fix is raising this
        # ceiling, not asking the agent to view smaller/degraded images.
        max_buffer_size=50 * 1024 * 1024,  # 50MB - generous headroom, sandbox has 1GB+ RAM
    )

    transcript = []
    result = None
    turn_count = 0
    # FINDING (2026-08-10): a run that dies mid-conversation previously lost
    # its transcript entirely, since it was only written once at the very
    # end - and there was no way to tell "slow" from "stuck" from outside
    # (this is what caused the confusion during the earlier interrupted
    # run). Heartbeat + periodic transcript checkpoints fix both: anyone can
    # check Storage mid-run and see recent activity, and a mid-run death
    # still leaves a partial transcript behind instead of nothing.
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

    # Final transcript write+upload - deterministic harness code, not an
    # agent decision, since by this point the agent's own turn is over.
    # Still runs inside the sandbox, still the run's own process, not an
    # external backend reaching in after the fact. Redundant with the last
    # checkpoint above in the common case, but guarantees the FINAL state
    # (including the ResultMessage) is captured even if turn_count wasn't a
    # multiple of the checkpoint interval.
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
