# Starter

Everything in here is input data. None of it is a starting point for your
build.

## What's in the packet

| | |
|---|---|
| `design-brains/kahua/`, `design-brains/emplifi/` | Two customers. `DESIGN.md`, `fonts/`, `brand/asset_manifest.json`, `brand/tokens.json`, staged logo files. |
| `inspirations/` | Reference designs from the two customers' own libraries. Deliberately outside both brains. |
| `design-engine/SKILL.md` | The contract for what a good asset looks like. Read it before you read anything here. |
| `starter/requests/*.example.json` | Two request payloads. See below. |
| Adstream | `https://adstream.bhairav.workers.dev/` — `demo@adstream.test` / `adstream`. The stand-in ads manager you deploy into. It is already running; you do not host it. |

## The two request files

`new-request.example.json` and `edit-request.example.json` are examples of
**what an operator submitted** — one new job, one edit against an existing
revision with two pinned comments on it.

That is all they are. Specifically:

- They are **not a schema.** Your storage model, your column names and your
  identifiers are yours. Do not treat these keys as a contract to conform to.
- They are **not a message format.** There is no envelope here, no queue field,
  no routing key, no correlation id. How a request reaches an agent is the
  question, not something we have answered.
- They are **not a test suite.** Two files are the shape of a request. The
  interleave — Emplifi opens a new task, Kahua opens one, Kahua edits theirs,
  Emplifi edits theirs, Emplifi opens a second — has to work in an order the
  system could not have anticipated, and nothing in here encodes that order on
  purpose. Build for arbitrary; do not build for these two.

The `inspirations` array is a list of exact filenames from `inspirations/`.
Empty means none attached.

## What this deliberately is NOT

There is no scaffolding here, and that is the point. Specifically:

- **No hydration code.** Deciding what gets baked into an image, what gets
  mounted per run, and what the agent fetches with a credential is the centre
  of this trial. Handing you a `hydrate()` would hand you the answer.
- **Nothing that decides what runs, when, or where.**
- **Nothing that gets work off a box, and no `RESULT.json` schema.** How the
  agent's output survives a sandbox that is about to be destroyed is yours to
  design, including what happens when it gets it wrong.
- **No sandbox template, Dockerfile, or provider config.**
- **No renderer.** HTML to PNG is a decision, not a utility we forgot to ship.
- **No database schema, migration, or bucket layout.**
- **No front end.**
- **No generated ads to compare against.** There is no reference output. What
  good looks like is in `SKILL.md`, in the brands' own `DESIGN.md`, and in
  `inspirations/`.

If something here would have saved you an hour, it was probably an hour we
wanted to watch you spend.

## Where to start

`SKILL.md`, then both `DESIGN.md` files, then the inspirations. Get the skill
generating ads you would actually show a customer — both brands, all four
canvas sizes — in your own Claude Code or Codex, before you touch a sandbox.
Everything downstream is undebuggable until that part is boring.
