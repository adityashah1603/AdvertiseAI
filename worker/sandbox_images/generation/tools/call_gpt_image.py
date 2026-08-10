"""
Thin wrapper around the OpenAI Images API for plate generation.

This is a TOOL, not the skill. The composition, lighting, palette, texture
and negative-space decisions belong to whoever calls this (a human during
Phase 0; the in-sandbox agent from Step 3 onward) - this script only knows
how to make the API call, reconcile gpt-image-2's size constraint against
the exact canvas the request needs, and save the result.

Usage:
    python call_gpt_image.py --prompt-file plate_prompt.txt --width 1080 --height 1080 --out plate.png

CONFIRMED FINDING (BUILD_GUIDE.md Step 1, 2026-08-10): gpt-image-2 rejects
any size where width or height is not divisible by 16. None of the four
required canvases (1080x1080, 1200x628, 1080x1350, 728x90) are natively
divisible by 16 - this is not an edge case, it's every required size.

Fix applied here: generate at the nearest size that (a) has the *exact same*
aspect ratio as the requested canvas and (b) has both dimensions divisible
by 16, then do a single uniform resize (identical scale factor on both axes)
down/up to the exact requested pixel dimensions. Because the generated
image's aspect ratio matches the target ratio exactly before resizing, this
is a uniform scale, not a crop/stretch/reframe - SKILL.md prohibits
reframing a plate into a *different* aspect ratio, which this isn't.

REAL API BOUNDS (confirmed 2026-08-10 against developers.openai.com/api/docs
/guides/image-generation directly, not an aggregator - see
phase0/README.md finding #2b for the full writeup):
  - max edge length <= 3840px
  - both edges must be multiples of 16px (matches what we'd already found
    empirically)
  - long-edge:short-edge ratio must not exceed 3:1 (matches what we'd
    already found empirically)
  - total pixel count must be between 655,360 and 8,294,400 inclusive -
    this one was NOT previously known and is a second, independent reason
    728x90 can never work: even the 1424x176 candidate this script tried
    earlier (see the 2026-08-10 finding above) was only 250,624 total
    pixels, well under the 655,360 floor, on top of failing the 3:1 ratio
    check. No minimum edge length is documented - the practical minimum
    edge comes from the total-pixel floor combined with the 3:1 ratio cap.
"""
import argparse
import base64
import os
import sys

from dotenv import load_dotenv

load_dotenv()

# Real documented bounds (see the note above) - not a guess.
MAX_EDGE = 3840
MIN_TOTAL_PIXELS = 655_360
MAX_TOTAL_PIXELS = 8_294_400
MAX_RATIO = 3.0

# Any candidate within this ratio error is "close enough" - the final resize
# step maps generated (w,h) directly onto the exact target (w,h), so a
# residual ratio error this small (well under a tenth of a percent) shows up
# as a sub-pixel stretch on a ~1000px image, not a visible distortion. Below
# this threshold, prefer the candidate closest to the target's actual pixel
# area (cheaper/faster to generate, less upscaling) over chasing more
# decimal places of ratio accuracy nobody could see.
RATIO_CLOSE_ENOUGH = 0.001


def nearest_multiple_of_16_same_ratio(target_w, target_h):
    """Find (w, h), both multiples of 16, whose ratio matches target_w/target_h
    closely enough (see RATIO_CLOSE_ENOUGH), within the API's real edge/area/
    ratio bounds, preferring a pixel area close to the target's among those."""
    ratio = target_w / target_h
    if ratio > MAX_RATIO or ratio < 1 / MAX_RATIO:
        raise ValueError(
            f"{target_w}x{target_h} has ratio {ratio:.4f}, which exceeds the API's "
            f"documented {MAX_RATIO}:1 maximum. No resize/rounding fixes this - "
            f"the requested shape itself is not generatable in one call."
        )
    best = None
    for h in range(16, MAX_EDGE + 1, 16):
        w = round((h * ratio) / 16) * 16
        if w < 16 or w > MAX_EDGE:
            continue
        total = w * h
        if total < MIN_TOTAL_PIXELS or total > MAX_TOTAL_PIXELS:
            continue
        ratio_err = abs((w / h) - ratio) / ratio
        area_err = abs(total - (target_w * target_h))
        # Bucket ratio error into "close enough" (0) vs "not" (1). Within a
        # bucket, area_err alone decides - ratio_err is deliberately NOT a
        # sort key here, or tuple comparison would fall through to it on
        # every tie and reintroduce the exact bug this bucketing exists to
        # fix (chasing decimal places of ratio accuracy over generation cost).
        bucket = 0 if ratio_err <= RATIO_CLOSE_ENOUGH else 1
        score = (bucket, area_err)
        if best is None or score < best[0]:
            best = (score, w, h)
    if best is None:
        raise ValueError(
            f"No divisible-by-16 size near {target_w}x{target_h} satisfies both the "
            f"{MIN_TOTAL_PIXELS}-{MAX_TOTAL_PIXELS} total-pixel range and the "
            f"{MAX_RATIO}:1 ratio cap - this shape isn't generatable in one call."
        )
    return best[1], best[2]


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prompt", help="Prompt text inline")
    group.add_argument("--prompt-file", help="Path to a file containing the prompt text")
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    prompt = args.prompt
    if args.prompt_file:
        with open(args.prompt_file, "r", encoding="utf-8") as f:
            prompt = f.read()

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY is not set - nothing to do.", file=sys.stderr)
        sys.exit(1)

    from openai import OpenAI

    client = OpenAI(api_key=api_key)

    target_w, target_h = args.width, args.height
    if target_w % 16 == 0 and target_h % 16 == 0:
        gen_w, gen_h = target_w, target_h
    else:
        gen_w, gen_h = nearest_multiple_of_16_same_ratio(target_w, target_h)
        print(f"{target_w}x{target_h} isn't divisible by 16 (gpt-image-2 requirement) - "
              f"generating at {gen_w}x{gen_h} (same aspect ratio) and resizing down to exact bounds.")

    size = f"{gen_w}x{gen_h}"

    try:
        result = client.images.generate(
            model="gpt-image-2",
            prompt=prompt,
            size=size,
            n=1,
        )
    except Exception as e:
        print(f"Image generation FAILED for size {size}: {e}", file=sys.stderr)
        print("If this is a size-rejection error, that's a Step 1 finding - "
              "record it, don't work around it by reframing a different plate.",
              file=sys.stderr)
        sys.exit(1)

    b64 = result.data[0].b64_json
    raw_bytes = base64.b64decode(b64)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)

    if (gen_w, gen_h) != (target_w, target_h):
        from io import BytesIO

        from PIL import Image

        img = Image.open(BytesIO(raw_bytes)).convert("RGB")
        img = img.resize((target_w, target_h), Image.LANCZOS)
        img.save(args.out)
        print(f"Saved {args.out} (generated {gen_w}x{gen_h}, uniformly resized to {target_w}x{target_h})")
    else:
        with open(args.out, "wb") as f:
            f.write(raw_bytes)
        print(f"Saved {args.out} ({size})")


if __name__ == "__main__":
    main()
