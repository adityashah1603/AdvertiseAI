# docs/

Planning, decisions, and findings from building this project. Paths
mentioned inside these documents (e.g. `design-brains/emplifi/DESIGN.md`,
`SKILL.md`) are relative to the repository root, not to this folder.

| Doc | What it is |
|---|---|
| `ROADMAP.md` | The architecture and why — the engineering plan on top of the product spec (`SKILL.md`). Start here. |
| `BUILD_GUIDE.md` | The literal, ordered task list used to build this, with a definition of done per step. |
| `DECISIONS.md` | The policy answers this project locked in, and why each one was chosen over the alternatives. |
| `FLOW.md` | How a request actually moves through the system in every scenario that's been hit or tested. Companion to `DECISIONS.md` (the why); this is the what/when. |
| `FINDINGS.md` | Things discovered while building — brand data inconsistencies, image-generation constraints, sandbox/SDK limits, deployment quirks. |
| `CharacterQuilt work trial - design engine.docx` | The original work trial brief. |

`SKILL.md` (the agent's product spec) stays at the repository root — it's
read at runtime by `worker/hydration/generation.py`, not just documentation.
