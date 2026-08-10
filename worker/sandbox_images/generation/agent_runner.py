"""
agent_runner.py - the autonomous version of what I (the outer Claude Code
session) did by hand in Phase 0: read the brand, generate a plate, build
the HTML overlay, render it, look at it, save it. Same job, no human
steering it turn by turn.

Deliberately minimal custom tooling. The Claude Agent SDK gives the agent
Bash/Read/Write/Glob for free - it's literally Claude Code as a library,
and its Read tool is already multimodal (can view a PNG it just rendered),
which is exactly what SKILL.md's "look at it" step needs. So the only
"tools" this agent gets beyond the SDK's built-ins are the two CLI scripts
already proven in Phase 0 (tools/call_gpt_image.py, tools/render_html.py) -
the agent calls them via Bash, exactly like I did by hand. No custom
@tool-wrapped Python functions were needed for this.

Tool availability is restricted via `tools=[...]` (the base set), not
`allowed_tools` - allowed_tools only controls auto-approval within a
permission_mode that still prompts, which is moot once permission_mode is
"bypassPermissions" (required here since no human is present inside a
sandbox to approve anything).

Expects to run with its working directory set to the root of a hydrated
file tree (see worker/hydration/generation.py):
  skill/SKILL.md
  skill/tools/call_gpt_image.py
  skill/tools/render_html.py
  brand_kit/DESIGN.md
  brand_kit/fonts/...
  brand_kit/brand/...
  job/request.json

NOT yet wired: saving results to Supabase Storage via a per-run signed
upload URL (ROADMAP.md SS4.1 step 5) - the orchestrator that mints those
URLs doesn't exist yet. For now the agent saves to ./output/ on local
disk, which is what makes this script testable on its own, before E2B is
wired in - proving the agent's actual behavior is a separate concern from
proving the sandbox plumbing works, same discipline as every other Phase 1
piece so far.
"""
import asyncio
import json
import sys
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    query,
)


def load_context(root: Path):
    skill_md = (root / "skill" / "SKILL.md").read_text(encoding="utf-8")
    job = json.loads((root / "job" / "request.json").read_text(encoding="utf-8"))
    return skill_md, job


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

Save every artifact for a canvas named <name> under ./output/<name>/:
  plate.png     - the raw generated plate
  overlay.html  - the HTML overlay (live text/logo, per the contract)
  render.png    - the final composited canvas, produced by render_html.py

When every canvas is done, write ./output/RESULT.json summarizing what you
built, any brand-data inconsistencies you found and how you resolved them,
and anything you could not do and why - the same spirit as the findings
already logged in phase0/README.md, but for this specific run.
"""


def build_task_prompt(job: dict) -> str:
    canvases = "\n".join(f"  - {c['name']}: {c['width']}x{c['height']}" for c in job["canvases"])
    return f"""New generation request.

Campaign: {job['campaign']}
Copy:
{json.dumps(job['copy'], indent=2)}

Canvases required:
{canvases}

Inspirations attached: {job['inspirations'] or 'none'}

Generate a complete, on-brand ad for every canvas size listed above,
following the skill contract in your system prompt. Look at each render
before considering it done.
"""


def _message_to_dict(message):
    if hasattr(message, "__dict__"):
        return {"type": type(message).__name__, **message.__dict__}
    return {"type": type(message).__name__, "value": str(message)}


async def run(root: Path):
    skill_md, job = load_context(root)

    options = ClaudeAgentOptions(
        system_prompt=build_system_prompt(skill_md),
        cwd=str(root),
        tools=["Bash", "Read", "Write", "Glob"],
        permission_mode="bypassPermissions",  # no human present to approve tool calls
        model="claude-sonnet-5",
        max_turns=60,
        max_budget_usd=5.0,  # safety cap - a runaway loop shouldn't be a silent surprise bill
    )

    transcript = []
    result = None

    async for message in query(prompt=build_task_prompt(job), options=options):
        transcript.append(message)
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    print(f"[agent] {block.text}")
                elif isinstance(block, ToolUseBlock):
                    print(f"[tool call] {block.name} {json.dumps(block.input)[:200]}")
        elif isinstance(message, ResultMessage):
            result = message

    # Saved regardless of success - ROADMAP.md SS6 ("runs save their own
    # agent transcripts") and the brief both want the raw transcript even
    # when a run fails.
    transcript_path = root / "output" / "agent-transcript.jsonl"
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    with open(transcript_path, "w", encoding="utf-8") as f:
        for message in transcript:
            f.write(json.dumps(_message_to_dict(message), default=str) + "\n")

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
