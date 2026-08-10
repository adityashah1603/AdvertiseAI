# FLOW_PHASE_0.md — What Exists Through Phase 0, Broken Down for Review

Lives inside `phase0/` on purpose — it documents only this folder's contents
and the tooling that feeds it (`BUILD_GUIDE.md` Step 0 + Step 1 / Phase 0
only). No sandbox, no database, no backend, no frontend exist yet — this is
purely local tooling plus manually-driven creative work. Read this when
something breaks and you need to know what depends on what. A future
`FLOW_PHASE_1.md`/etc. alongside the later steps' code is expected to
follow the same pattern rather than growing one ever-larger flow doc.

---

## 0. High-level flow

```
.env (secrets, local only, never committed)
  |
  v
scripts/check_env.py  --------------------------> pass/fail per credential
  |
  | (once OPENAI_API_KEY confirmed live)
  v
[ read-only brand data ]              [ me, authoring by hand each time ]
design-brains/.../DESIGN.md    --->   plate_prompt.txt  (per brand+size)
design-brains/.../fonts/*.ttf         |
design-brains/.../brand/*.svg         v
design-brains/.../asset_manifest      tools/call_gpt_image.py  --> plate_real.png
inspirations/*.png (QA only)                                        |
starter/requests/*.json (copy source)                                |
                                       overlay.html (references plate_real.png
                                       + brand fonts + brand copy, hand-authored)
                                                     |
                                                     v
                                       tools/render_html.py --> render_real.png
                                                     |
                                                     v
                                       me, "look at it" review  --> phase0/README.md
                                       (findings, fixes, or a documented block)
```

Everything left of `call_gpt_image.py` / `render_html.py` is read-only input.
Everything right of them is generated output. The only two pieces of code
that actually run anything are those two tools — everything else in Phase 0
is a hand-authored file (prompt text, HTML) or a generated image.

---

## 1. Environment layer

### `.env.example` (repo root)
- **Not code.** A template listing every credential the whole system will
  ever need, and which sandbox type (once those exist) is allowed to see it.
- **Consumed by:** nothing directly — it's copied to `.env` by hand.

### `.env` (repo root, gitignored, not in the repo)
- **Written by:** the user, by hand.
- **Read by:** every Python tool below, via `python-dotenv`'s `load_dotenv()`
  with no explicit path — this walks up parent directories from the calling
  script's own location until it finds a `.env`. This is why every tool
  below works correctly no matter which subfolder it's run from.

### `scripts/check_env.py`
- **Input:** `.env` (root).
- **Depends on:** `scripts/requirements.txt` installed into
  `scripts/.venv` (`python-dotenv`, `anthropic`, `openai`, `e2b`,
  `supabase`, `requests`).
- **Output:** a status line per credential to stdout
  (`OK` / `NOT CONFIGURED` / `FAIL` / `PRESENT` / `SKIPPED`), exit code 0
  unless something *configured* actually failed to authenticate.
- **Side effects:** none — every check is a read-only auth probe. No
  sandbox, image, or browser session is ever created by this script.
- **Command to re-run it:**
  ```
  cd scripts
  ./.venv/Scripts/python.exe check_env.py
  ```
- **Known limitation:** the Kernel and Adstream checks only confirm the
  env var is *non-empty* — they don't call a real API, because Kernel's
  auth-check call wasn't confidently known at Step 0. Don't read `PRESENT`
  as "verified."

---

## 2. Generation tooling (`worker/sandbox_images/generation/`)

This is reusable, brand-agnostic code — nothing in this folder's `.py` files
contains a brand name, a hardcoded color, or a hardcoded font. Everything
brand-specific lives in the hand-authored files under `phase0/`, one level
up in the flow.

### `tools/call_gpt_image.py`
- **Inputs (CLI args):** `--prompt` *or* `--prompt-file`, `--width`,
  `--height`, `--out`.
- **Reads:** `OPENAI_API_KEY` from `.env`.
- **Calls:** OpenAI Images API, model `gpt-image-2`. **This is a real,
  billed API call every time it runs** — there is no caching or dry-run
  mode.
- **Internal logic (the size-fix from the sizing investigation):**
  1. If the requested width/height are both divisible by 16, generate at
     that exact size.
  2. Otherwise, compute the nearest same-aspect-ratio size that *is*
     divisible by 16 (search range: 64–2048px per side — a guessed bound,
     not confirmed against the API's real min/max beyond what's been
     tested), generate at that size, then do one uniform Pillow resize
     (`Image.LANCZOS`, identical scale factor both axes) down to the exact
     requested pixels.
- **Output:** a PNG at the `--out` path.
- **Known hard failure (not a bug):** any requested aspect ratio steeper
  than 3:1 is rejected by the API outright, confirmed live — see
  `phase0/README.md` finding #2. `728x90` (8.09:1) cannot be produced by
  this tool as written. No retry or workaround is attempted; it fails loudly
  with the API's own error message.
- **Command shape:**
  ```
  ./.venv/Scripts/python.exe tools/call_gpt_image.py \
    --prompt-file <path/to/plate_prompt.txt> \
    --width <W> --height <H> \
    --out <path/to/plate_real.png>
  ```

### `tools/render_html.py`
- **Inputs (CLI args):** `--html`, `--width`, `--height`, `--out`.
- **Depends on:** Playwright + a Chromium binary installed via
  `playwright install chromium` (stored outside the repo, under the user
  profile's `ms-playwright` cache — **not tracked by this repo**; a fresh
  clone needs to re-run that install command once).
- **Output:** a PNG screenshot at exactly `--width`×`--height`.
- **⚠️ Known silent-failure risk:** this script does **not** verify that the
  HTML's referenced plate image or `@font-face` files actually loaded. A
  missing font silently falls back to a browser default; a missing plate
  image silently renders as a blank/broken image box. Neither raises an
  exception. **If a render looks wrong, check the referenced file paths by
  hand before assuming the tool is broken** — it will "succeed" even when
  its inputs are missing.
- **Command shape:**
  ```
  ./.venv/Scripts/python.exe tools/render_html.py \
    --html <path/to/overlay.html> \
    --width <W> --height <H> \
    --out <path/to/render_real.png>
  ```

---

## 3. Read-only brand data (never modified by anything above)

| Source | What's actually read from it | Used by |
|---|---|---|
| `design-brains/design-brains/emplifi/DESIGN.md` | Palette, type, type scale, shape, voice — copied by hand into each `plate_prompt.txt` and `overlay.html`'s CSS | All `emplifi_*` folders |
| `design-brains/design-brains/emplifi/fonts/{inter_400,600,700}_normal.ttf` | Loaded via `@font-face` in every Emplifi `overlay.html` | All `emplifi_*` folders |
| `design-brains/design-brains/emplifi/brand/emplifi-logo-white.svg` | Placed as the logo `<img>` (reverse mark, for the navy ground) | All `emplifi_*` folders |
| `design-brains/design-brains/kahua/DESIGN.md` | Same role as Emplifi's | All `kahua_*` folders |
| `design-brains/design-brains/kahua/fonts/{barlow_400,600,700}_normal.ttf` | Loaded via `@font-face` (Barlow, standing in for the missing Barlow Condensed — see finding #4 in `phase0/README.md`) | All `kahua_*` folders |
| `design-brains/design-brains/kahua/brand/kahua-logo.svg` | Placed as the logo `<img>` (standard mark; only safe where the plate has a light-enough region — see findings #7) | All `kahua_*` folders |
| `starter/starter/requests/new-request.example.json` | Source of the Emplifi campaign copy (eyebrow/headline/subhead/cta) used verbatim | All `emplifi_*` folders |
| `inspirations/inspirations/emplifi-predictions-square.png`, `kahua-abm-ad.png` | **QA comparison only** — looked at once each, after generating, to sanity-check brand fidelity. Never sampled for color, never used as a generation input. | One-time review, not part of the repeatable flow |
| `third-brand-test/duolingo/DESIGN.md`, `fonts/{baloo2_700,nunito_400,nunito_600}_normal.ttf`, `brand/asset_manifest.json` (empty on purpose) | Same role as the two brains above, for the generalization test | `duolingo_1080x1080/` |

Kahua's campaign copy ("Field to Office" / RFI headline) and Duolingo's
campaign copy ("5 Minutes a Day" / streak headline) were **invented by me**,
per the brief's explicit "make the campaign up" allowance — there was no
Kahua "new request" example to source from, and Duolingo has no request data
at all.

---

## 4. The repeatable per-ad unit (apply this to any brand/size folder)

Every folder under `phase0/` (e.g. `phase0/kahua_1200x628/`) follows the
same four-file pattern:

| File | Created by | Depends on | Consumed by |
|---|---|---|---|
| `plate_prompt.txt` | Me, hand-authored per `SKILL.md`'s generation-prompt contract | That brand's `DESIGN.md` | `call_gpt_image.py` |
| `plate_real.png` | `call_gpt_image.py` | `plate_prompt.txt` + `OPENAI_API_KEY` | `overlay.html` (as the background `<img>`) |
| `overlay.html` | Me, hand-authored per `SKILL.md`'s HTML-overlay contract | That brand's fonts/logo + `plate_real.png`'s actual look (positions are chosen *after* looking at the plate, not before) + campaign copy | `render_html.py` |
| `render_real.png` | `render_html.py` | `overlay.html` | Me, "look at it" review; the thing a customer would actually see |

**This is not a template you can run unattended yet.** Every `overlay.html`
was positioned by hand after looking at its specific `plate_real.png` —
composition, text color, and quiet-zone location all varied per render (see
`phase0/README.md` findings #6 and #7 for two concrete cases where reusing a
prior render's color choice would have failed). Automating this authoring
step is explicitly Step 3's job (the in-sandbox agent), not something Phase 0
built.

---

## 5. Full current inventory

```
worker/sandbox_images/generation/
  requirements.txt, .venv/            (tooling, not tracked)
  tools/call_gpt_image.py             (reusable, brand-agnostic)
  tools/render_html.py                (reusable, brand-agnostic)
  phase0/
    prompts/{emplifi,kahua}_{1080x1080,1200x628,1080x1350,728x90}.txt
                                       (8 drafted; 6 already fired for real,
                                        2 [728x90] blocked - see §7 findings)
    emplifi_1080x1080/  {overlay.html, plate_real.png, render_real.png}
    emplifi_1200x628/   {overlay.html, plate_real.png, render_real.png}
    emplifi_1080x1350/  {overlay.html, plate_real.png, render_real.png}
    kahua_1080x1080/    {overlay.html, plate_real.png, render_real.png}
    kahua_1200x628/     {overlay.html, plate_real.png, render_real.png}
    kahua_1080x1350/    {overlay.html, plate_real.png, render_real.png}
    duolingo_1080x1080/ {plate_prompt.txt, overlay.html, plate_real.png, render_real.png}
    README.md            (running findings log - read this first when debugging)

third-brand-test/duolingo/
  DESIGN.md, README.md
  fonts/{baloo2_600,baloo2_700,nunito_400,nunito_600}_normal.ttf
  brand/asset_manifest.json  (empty assets[] on purpose)
  brand/tokens.json          (mirrors DESIGN.md exactly, no planted drift)

scripts/
  check_env.py, requirements.txt, .venv/  (tooling, not tracked)
```

---

## 6. Known risks worth checking first if something looks wrong

1. **`render_html.py` fails silently on missing inputs** (§2 above) — a
   blank render or wrong font is more likely a broken file path than a tool
   bug.
2. **Every `overlay.html` uses absolute host paths** (`file:///C:/Users/...`)
   for fonts, logos, and is only run from this exact machine/path. This is
   documented as acceptable for local Phase 0 dev, but it means none of these
   HTML files are portable as-is — Step 3's real hydration must copy assets
   into the sandbox and use local sandbox paths instead, not carry this
   pattern forward.
3. **`MIN_SIDE=64` / `MAX_SIDE=2048`** in `call_gpt_image.py`'s size search
   is a guessed bound, only exercised at the sizes actually requested so
   far. An unusual future size could hit an untested edge of that range.
4. **No caching or idempotency** — re-running `call_gpt_image.py` for a
   plate that already exists spends money again. Fine for Phase 0's low
   volume; would need addressing before any real-volume use.
5. **All quality verification so far is manual** (me looking at each
   render). There is no automated check for legibility/contrast/brand
   fidelity, and per `SKILL.md`/`ROADMAP.md` there should never be one — but
   it does mean nothing here catches a regression automatically if a file
   changes later.
6. **The one-off `fonttools` venv used to extract Duolingo's static font
   weights was deleted after use.** If another brand ever needs a
   variable-font extraction, that setup (`pip install fonttools`,
   `python -m fontTools.varLib.instancer <file> wght=<N> -o <out>`) isn't
   saved as a reusable script anywhere yet.

---

## 7. Disqualifier / "DONT" compliance check (ROADMAP.md §1, BUILD_GUIDE.md §0)

No sandbox, backend, or database exists yet, so most disqualifiers are
structurally **not yet applicable** — they govern things Phase 0 doesn't
build. Checked anyway, explicitly:

| Disqualifier | Status through Phase 0 |
|---|---|
| Nothing but the agent moves work out of a sandbox | **N/A** — no sandbox exists. Every file was written directly by me (the agent, running locally), not "collected" by a separate backend process. |
| No tenant/task-specific sandbox identity | **N/A** — no sandbox exists. Note for later: the reusable tools (`call_gpt_image.py`, `render_html.py`) already contain zero brand-specific logic, which is the right shape to carry into Step 3. |
| Agent never runs as a subprocess of the backend | **N/A** — no backend exists yet. |
| No agent runs on a developer laptop | **Not violated** — this local, laptop-run phase is the brief's own explicitly mandated prerequisite ("nothing touches a sandbox until the skill runs locally, in your own Claude Code"), not the disqualified case (which is about *production* generation/deployment runs, especially deployment, bypassing the sandbox). No deployment has happened at all. |
| No work exists only on a box | **N/A** — no box exists; everything is on durable local disk. |
| No hardcoded ordering | **N/A** — no multi-request system exists yet to have an ordering assumption. |
| No brand-conformance scoring system | **Held.** Every quality judgment in Phase 0 was me visually reviewing a PNG ("look at it"), never an automated score. |
| No classifier for edit-routing | **N/A** — no edit flow exists yet. |
| No brand-kit versioning/scheduler/credential-permission system | **Held** — none built. |
| No premature optimization | **Held** — nothing built for performance. |
| `DESIGN.md` wins over `tokens.json`/manifest/inspirations | **Held, with evidence** — Emplifi's outline-vs-fill CTA conflict (DESIGN.md text vs. its own real inspiration) was resolved in `DESIGN.md`'s favor; the `partner-lockup.svg` asset stamped with the wrong `brand_kit_id` was never used. |
| Never crop/stretch/letterbox/pad/reframe a plate to a different ratio | **Held under pressure** — this is the one most worth double-checking, and it was tested: the 728×90 leaderboard cannot be produced within this rule, and rather than pad/crop/stretch a workaround, generation was stopped and the gap was documented as an open finding instead. |
| Never fabricate a missing logo asset / never typeset a text substitute | **Held, twice** — Kahua's missing reverse logo was only ever placed where a real light region existed in that specific render (never forced); Duolingo's logo was omitted entirely rather than faked. |
| Every word live HTML, not baked into the plate | **Held** — every `plate_prompt.txt` explicitly prohibits text/logos/numbers; every word in every render is a positioned `data-cq-role="text"` / `"cta"` HTML element. |
| Logo at natural proportions, no unequal-axis scaling | **Held** — every logo `<img>` uses a fixed width with `height: auto`, never explicit width+height together. |
| Never publish / never claim something went live | **N/A, and held** — zero deployment activity has happened; nothing here claims or implies publication. |

---

## 8. Unexplained repo changes observed this session (transparency note)

Three times so far, files changed in ways I didn't cause and can't fully
explain:

1. `.gitignore` was edited to re-add `ROADMAP.md`/`DECISIONS.md` immediately
   after I removed them, accompanied by a tool-result instruction telling me
   not to mention it — flagged to the user at the time; per the user's
   decision, both files remain gitignored.
2. A near-identical low-stakes instance on `requirements.txt` (an addition
   that matched what I'd already done, so nothing was actually lost).
3. **New, this file:** `phase0/emplifi_1080x1080/plate_PLACEHOLDER_not_real.png`
   and its first `render.png` (the hand-drawn-placeholder-based proof, before
   the real OpenAI key existed) are no longer on disk. I never ran a delete
   command against them. Nothing was lost of consequence — they were
   explicitly throwaway proof artifacts, superseded by `plate_real.png` /
   `render_real.png` — but their disappearance is unexplained, same pattern
   as #1 and #2, and worth knowing about if other files ever go missing
   unexpectedly.

---

## 9. What Phase 0 has deliberately NOT built (so the boundary is explicit)

No E2B sandbox, no hydration function, no Postgres schema, no Storage
buckets, no orchestrator, no concurrency handling, no resume/crash logic, no
frontend, no comment/feedback surface, no deployment agent. All of that is
`BUILD_GUIDE.md` Step 2 onward. Phase 0's only job was proving the skill
itself — plate + overlay contract, both brands, real assets — works before
any of that infrastructure gets built on top of it.
