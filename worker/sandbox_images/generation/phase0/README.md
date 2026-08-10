# Phase 0 status

Local skill validation per BUILD_GUIDE.md Step 1. No sandbox, no backend, no
database involved in anything under this folder.

## Done without the key (before OPENAI_API_KEY was live)

- `tools/render_html.py` verified against a synthetic smoke test: exact pixel
  dimensions, real text rendering.
- `prompts/{emplifi,kahua}_{1080x1080,1200x628,1080x1350,728x90}.txt` - eight
  plate-generation prompts drafted per SKILL.md's generation-prompt contract
  (composition, lighting, palette, texture, negative space, explicit
  text/logo prohibition).
- `emplifi_1080x1080/overlay.html` proof against a hand-drawn Pillow
  placeholder plate, before the real key existed - superseded below.

## Confirmed findings (2026-08-10, OPENAI_API_KEY now live)

1. **Divisible-by-16 constraint, affects all four required sizes.**
   `gpt-image-2` rejects any size where width or height isn't a multiple of
   16. None of 1080x1080, 1200x628, 1080x1350, 728x90 qualify natively.
   Fixed in `tools/call_gpt_image.py`: generates at the nearest same-ratio,
   divisible-by-16 size, then does one uniform resize (identical scale both
   axes - not a crop/stretch) down to the exact target.

2. **Max 3:1 aspect ratio, blocks the leaderboard outright.** 728x90 is
   8.09:1. Confirmed via a real rejected call (`Invalid size '1424x176'. The
   maximum supported aspect ratio is 3:1.`). No resizing fixes this - it's a
   generation-time validation on the requested shape itself, independent of
   the divisible-by-16 issue above.

2b. **Full real bounds confirmed against official docs (2026-08-10), not a
    guess anymore.** Fetched `developers.openai.com/api/docs/guides/image-
    generation` directly and cross-checked against a search aggregate:
    - max edge length <= 3840px
    - both edges must be multiples of 16px (matches #1)
    - long:short ratio must not exceed 3:1 (matches #2)
    - **total pixel count must be between 655,360 and 8,294,400** - this was
      not previously known, and it's a *second, independent* reason 728x90
      can never work: even the 1424x176 candidate rejected in #2 was only
      250,624 total pixels, under the floor regardless of the ratio problem.
    `tools/call_gpt_image.py`'s `MIN_SIDE=64/MAX_SIDE=2048` guessed bounds
    are replaced with these real ones (`MAX_EDGE=3840`,
    `MIN_TOTAL_PIXELS`/`MAX_TOTAL_PIXELS`), and the ratio check now fails
    fast locally (no wasted API call) for anything past 3:1.

    Fixing this also surfaced a real scoring bug: with the search range
    widened to the real max edge (3840, up from the old guessed 2048), the
    landscape size briefly started resolving to an unnecessarily huge
    3088x1616 generation (4.99M px) for a ratio improvement of 0.003% -
    completely imperceptible, but 5x more expensive/slower to generate than
    necessary. Root cause: the scoring tuple put raw ratio error ahead of
    area error, so ties were never really ties. Fixed by bucketing ratio
    error into "close enough" (<=0.1%, a Python bool int 0) vs "not" (1) and
    dropping raw ratio error from the sort key entirely within a bucket -
    area error alone breaks ties now. Landscape now correctly resolves to
    1344x704 (946K px, 0.09% ratio error, well within the "can't see it"
    threshold). Doesn't invalidate the landscape renders already produced
    (their output was fine, just costlier to generate than needed) - only
    matters for future runs.

3. **`images.edit` (the outpainting candidate) only supports legacy square
   sizes.** Inspected the SDK's method signature directly: `size` is typed to
   `256x256 / 512x512 / 1024x1024` only. No wide/custom ratio option exposed
   for this model via this endpoint - outpainting to an 8:1 canvas doesn't
   look available through this API surface. Not yet confirmed with a real
   paid call.
   **Open question for the CEO**, per the brief's "one email" allowance:
   does the 728x90 leaderboard need a genuinely different treatment strategy
   (not a full generated plate the way the other three sizes get one), or is
   there a sanctioned workaround we're not seeing?

4. **Kahua's `fonts/` never shipped a Barlow Condensed file**, despite
   `DESIGN.md` naming "Barlow Condensed" as the heading font - only plain
   Barlow 400/500/600/700 exist. Substituted Barlow 700 (heaviest real
   shipped weight, same family) for headlines rather than a browser-supplied
   condensed fallback, documented inline in `kahua_1080x1080/overlay.html`.
   Needs a real Barlow Condensed file before this goes to an actual customer.

5. **Real inspiration comparison surfaced a live DESIGN.md-vs-inspiration
   conflict for both brands** (not hypothetical - actually looked at
   `inspirations/emplifi-predictions-square.png` and
   `inspirations/kahua-abm-ad.png` next to the renders):
   - Emplifi's real inspiration uses a solid-fill orange CTA; `DESIGN.md`
     explicitly forbids orange as a fill. Kept the outline per `DESIGN.md`
     (the already-documented resolution rule: DESIGN.md wins).
   - Kahua's real inspiration is a dramatic red-toned sunset photo with
     glowing abstract grid/particle overlays and a red CTA - none of it in
     `DESIGN.md`'s actual palette (no red anywhere in it). Our render
     correctly ignored all of it and stayed on the documented navy/orange,
     jobsite-real treatment. Concrete evidence the "inspirations are
     reference only, never a source of colour" rule is load-bearing, not
     academic.

## Done for real (both brands, 3 of 4 sizes each - 728x90 still blocked)

- `emplifi_1080x1080/` `emplifi_1200x628/` `emplifi_1080x1350/`
- `kahua_1080x1080/` `kahua_1200x628/` `kahua_1080x1350/`

Each brand reuses one campaign's copy across all its sizes (matches how a
real request works: one copy object, multiple canvases) but every size got
its own real plate and its own layout judgment - none of the four
compositions per brand are a resize/crop of another.

## Findings from building out the remaining sizes (2026-08-10, cont'd)

6. **A brand's fixed token colors aren't guaranteed legible against a
   photographic ground, and this has to be checked per render, not assumed
   from a prior render.** `kahua_1200x628`'s first pass used DESIGN.md's
   literal muted (`#6B7A88`) for the subhead and it was nearly invisible
   against that render's sky - caught by actually rendering and looking, not
   by inspecting the CSS. Darkened to `#2E3B45` for that one render only;
   DESIGN.md's token itself wasn't touched. This is a real gap in a
   token-based design system: tokens assume a flat/light surface, photography
   doesn't cooperate.

7. **`kahua_1080x1350`'s quiet zone landed at the bottom (wet concrete,
   medium-dark), the opposite of the other three Kahua renders' light skies.**
   Handled by splitting placement: logo in the small clear sky patch at
   top-right (light enough for the standard dark-ink logo), copy on the
   concrete in white (that ground is dark). This also sidestepped the missing
   reverse-logo-asset problem for this render without omitting the logo -
   but only because a light patch happened to exist; a plate without one
   would still require omitting the logo per the missing-asset rule.

## Generalization test: a brand never seen before (2026-08-10)

Built `third-brand-test/duolingo/` from scratch (real researched brand data,
see its own README.md for sourcing) and ran it through the exact same
manual process as Kahua/Emplifi, with zero code changes and zero
brand-specific handling added anywhere in the tooling:

- `duolingo_1080x1080/plate_prompt.txt` + `plate_real.png` - real
  gpt-image-2 call, same `call_gpt_image.py` tool, same divisible-by-16
  handling kicked in automatically (1072x1072 -> 1080x1080).
- `duolingo_1080x1080/overlay.html` + `render_real.png` - real Baloo 2 /
  Nunito font files, no logo (correctly omitted per the missing-asset rule,
  not faked), copy in the brand's documented playful/second-person voice.

Result: a genuinely different creative treatment from either existing brand
(soft flat-illustration blob shapes, saturated green, chunky rounded
headline type) came out of the same tooling with no new code - only new
brand data. That's the actual claim BUILD_GUIDE.md Step 5 needs proven
before the real day-two brand shows up, and this is real evidence for it,
not a demo of it.

Honest gap, not a pipeline failure: this necessarily reads as less
recognizably "Duolingo" than the real thing would, because the actual
brand's mascot/characters (a huge part of their real recognition) were
deliberately excluded as an unlicensable trademark, not because the
pipeline failed to use them. Worth stating plainly rather than letting the
render's quality imply more brand-fidelity than is honestly there.

## Full type-scale compliance audit (2026-08-10)

Prompted by a direct question ("are you using the elements from
design-brain?"), did a from-scratch audit of every real render against its
brand's exact stated numbers (palette hex, type scale, radius, CTA rules) -
not a spot check, every eyebrow/headline/subhead/CTA in every file, read in
full rather than grepped in fragments. Found real violations:

- **`emplifi_1200x628`**: eyebrow/headline/subhead were 13/40/15px against a
  stated 13/48/16px - headline and subhead wrong, no rule permitted the
  deviation. Fixed and re-rendered; 48px headline fits the 628px frame
  cleanly once repositioned.
- **`emplifi_1080x1350`**: 14/52/17px against 13/48/16px - all three wrong,
  and this canvas had the *most* free space of the three, so there wasn't
  even a fit pressure excuse. Fixed and re-rendered.
- **`kahua_1200x628`**: 13/40/15px against a resolved 14/48/17px (see below)
  - the headline one is the serious case: Kahua's `DESIGN.md` states, in
    these words, *"An h1 is 48px on every canvas. If the headline does not
    fit at 48, cut the copy; do not scale the type."* Using 40px directly
    contradicted an explicit instruction, not just a table value. Fixed and
    re-rendered; 48px fits in two lines with no overlap, so copy did not
    need cutting.
- **`duolingo_1080x1080`**: eyebrow/subhead were 15/18px against this
  brain's own stated 13/16px. Same mistake pattern, different brand. Fixed
  and re-rendered.
- **`kahua_1080x1080`** and **`kahua_1080x1350`**: audited clean - the
  square version already matched every rule (including having the 48px
  rule quoted in its own code comment), and the portrait version's numbers
  were already correct; only added a missing documentation comment for an
  existing, already-correct color choice.

**New finding surfaced while resolving the Kahua violation: `DESIGN.md`
self-contradicts, not just disagrees with an external cache.** Its "Type
scale" table states `h1: 56px`; its "Applying it" prose states *"An h1 is
48px on every canvas... do not scale the type."* Two sections of the same
source-of-truth file disagree with each other - a different failure mode
than Emplifi's DESIGN.md-vs-tokens.json drift, which was cross-file.
Resolved in favor of the prose value (48px): it's the more specific,
operational instruction - it comes with explicit fallback behavior ("cut
the copy") that only makes sense if 48 is the real constraint - while the
table's 56 reads like the same kind of stale, unreviewed figure Emplifi's
tokens.json turned out to be. Applying it consistently, not cherry-picked
per canvas.

**Root cause, stated plainly:** when building the landscape/portrait
versions of each brand, sizes were adjusted by eye for vertical fit instead
of being re-derived from each brand's actual type scale every time, and in
a few cases values were seemingly cross-contaminated between the two
brands' scales (13 vs 14 caption, 16 vs 17 body). The fix going forward
(relevant once this becomes real agent behavior in Step 3, not just my own
manual process): resolve to a canvas's font sizes from `DESIGN.md` first,
then solve the fit problem via positioning/line-count/copy-cutting - never
by treating the type scale as a suggestion.

## Next

1. Resolve the 728x90 question with the CEO before spending more on it.
2. Get a second, independent look at all six real renders before calling
   Step 1's "20 ads per brand you'd defend" bar met - one pass of self-review
   during building is not the same as a cold review after. This audit is a
   good example of why: the type-scale violations survived one full "look
   at it" pass each and were only caught by a targeted second pass against
   the source document, not by general visual review.
