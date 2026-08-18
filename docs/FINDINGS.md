Few Things i found out while going through the work trial: 

Provided Brand Data:
1. Emplifi's DESIGN.md and its own tokens.json disagree on color, radius, and heading size.
2. Emplifi's asset manifest contains a logo asset stamped with a different customer's brand kit id.
3. Kahua's DESIGN.md contradicts itself — not a cross-file conflict, its own type-scale table says one number, its own prose says another.
4. Kahua's manifest references a reverse-logo file that was never actually shipped.

Image Generation:
1. All 4 canvases are natively invalid (requires a divisble by 16)
2. 728x90 fails the OpenAI image generatios as: 
   - max 3:1 aspect ratio
   - pixel floor of (655x360 pixels) - fails
3. Sizing bug - logic once picked 5x oversized image generation for a minimal aspect ratio improvement, fixed by making pixel area cost as tie breakers

Sandbox:
1. Used the default 1gb sandboxes, required a prebuilt template (just kept the dependencies - env in a sandbox initalized per fire so it doesnt have to redownload everytime it spins up)

Claude Agent SDK:
1. 1MB max IPC message size if exceeded could kill the whole session, raised to 50MB
2. Real successful run got misinterpreted as fail - non ASCII char crashed on windows control consol codepage, was marked failed even though work succeeded. 

Concurrency:
1. If a sandbox dies midrun(not due to an agent error), theres no way to recover/heal sandbox - heals on a timer not immediately - urgent fix on a larger scale

Deployment:
1. Adstream has no backend - need recording tried to fix why my run would show on refresh, found this out later
2. Adstream's deploy accepts only one image per ad, if we generate multiple we cant deploy all at once
3. Only 4 campaign types - maps to the closest one right now
4. Retrying stuck deploy doesnt resume - starts a new deploy attempt
5. Mid session kill is unrecoverable - need to restrat

