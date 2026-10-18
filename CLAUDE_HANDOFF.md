# Claude handoff: AvianVisitors_Weather2

## Suggested opening prompt

Continue the active frontend work in this repository. Start by reading this handoff, `README.md`, and the complete working-tree diff. Preserve all existing uncommitted changes unless you have a specific reason to alter them. Diagnose before editing. The immediate work appears focused on making the AvianVisitors frontend reliable and usable on iPad/Safari, especially the bird collage. Review the warnings and unresolved items below before implementing anything.

## Repository and environment

- Local repository: `C:\Users\white\PycharmProjects\AvianVisitors_Weather2`
- Current date when exported: 2026-07-29
- Shell: PowerShell on Windows
- Branch/HEAD was not explicitly queried; current commit is `6943ea1 feat: Add illustration bundle link to Iberian illustrations (#37)`.
- Product: AvianVisitors, a Raspberry Pi/BirdNET-Pi overlay that presents detected birds as a live collage. The main custom code is under `avian/`; the frontend is plain HTML, CSS, and JavaScript with PHP API shims.
- Main frontend files: `avian/frontend/index.html`, `avian/frontend/styles.css`, and `avian/frontend/apt.js`.
- Relevant supporting data/assets: `avian/frontend/dims.json`, `avian/frontend/masks.json`, `avian/assets/illustrations/`, `avian/assets/cutouts/`, and APIs under `avian/api/`.

## Conversation context available to export

The user first asked: "Export all of my stored memories and any context you've learned about me from past conversations. Preserve my words verbatim where possible, especially for instructions and preferences."

The assistant explained that no stored memories or past conversations were accessible from this session. The user then asked: "Export everything needed to move tis code conversation to claude" and linked `avian/frontend/styles.css`.

There is no additional user-stated feature request, acceptance criterion, or past-conversation history available in this session. Do not invent one; infer the active technical direction from the worktree, then confirm with the user if a decision would materially change behavior.

## Current working tree — preserve it

At export time:

```text
 M avian/frontend/apt.js
 M avian/frontend/index.html
 M avian/frontend/styles.css
?? avian/frontend/nest.svg
```

Diff size:

```text
avian/frontend/apt.js      +223 -28
avian/frontend/index.html  +11  -14
avian/frontend/styles.css  +95  -0
```

Use `git diff -- avian/frontend/apt.js avian/frontend/index.html avian/frontend/styles.css` to inspect the authoritative changes. `nest.svg` is untracked, so inspect it separately.

## What the uncommitted work is doing

- Moves the current view title (`#staticTitle`) from the former `.static-head` inside the stage into the fixed top bar and adds `.top-title` styling.
- Adds explicit/cached asset query strings for `styles.css` and `apt.js`.
- Gives the collage an explicit viewport-derived height and adds tablet/iPad coarse-pointer layout rules.
- Adds a conspicuous dashed red `COLLAGE CANVAS DEBUG BOX`; its own comment says to remove it when sizing is finalized.
- Makes collage image loading eager/synchronous to avoid blank absolutely-positioned images on iPad Safari.
- Coarsens the mask-packing occupancy grid from 4px to 8px on coarse-pointer devices.
- Contains a rectangular `renderSimpleCollage` fallback path, but `SIMPLE_COLLAGE` is currently hardcoded to `false`, so the normal mask-based circular collage remains active.
- Adds touch behavior: first tap highlights a bird, a second tap on the same silhouette within 360ms opens detail, and the highlight clears after 60 seconds.
- Adds a 30-second species-detail modal auto-close.
- Adds 1-hour-window behavior: after 30 seconds with no species, automatically select 12 hours; poll for 1-hour data and return to 1 hour when detections appear.
- Replaces the empty-state nest image with a CSS-drawn `.nest-mark`.
- Adds defensive null handling for the removed `.static-head` and possibly absent `#aboutLink`.
- Adds `nest.svg`, an unused standalone empty-nest illustration. The runtime now uses CSS `.nest-mark`, not this SVG or the existing `nest.webp`.

## Important warnings / likely unresolved issues

1. `avian/frontend/index.html` has likely accidental encoding damage. Its diff adds a UTF-8 BOM and converts visible characters as follows:
   - `→` to `â†’`
   - `·` to `Â·`
   - `×` to `Ã—`
   Review and repair these without discarding the intended structural edits.
2. The repo's displayed `README.md` also contains mojibake in this Windows reading context (for example `â‰¥` and broken tree glyphs). Determine whether that is file corruption or terminal decoding before touching it.
3. Comments around `SIMPLE_COLLAGE` claim an iOS 12 fallback, but the flag is always `false`; the fallback is dead unless enabled elsewhere (it is not, based on the searched references).
4. The simple fallback creates `.gtile` elements but does not populate `collagePlaced`; the existing silhouette hit-test/touch path therefore may not interact with those tiles if the fallback is enabled.
5. CSS still contains many `.static-head` rules even though the corresponding markup was removed. Some may now be dead. Title fade behavior falls back to immediate text replacement because `staticHead` is null.
6. `index.html` uses an inline collage height of `calc(100vh - 300px)`, while the tablet media query overrides it with `calc(100vh - 190px) !important`; clarify which size is intended and test portrait/landscape.
7. The red debug outline is currently user-visible.
8. Cache-buster names (`ios12-collage-1` and `ios12-collage-20`) look temporary and inconsistent.
9. No tests or browser validation were run during this export. The target issue appears browser/device-specific, so validate at least desktop behavior plus iPad/Safari or an appropriate simulator/device.
10. Do not reset, checkout, or overwrite the uncommitted work. It belongs to the user.

## Useful commands

```powershell
git status --short
git diff --stat
git diff -- avian/frontend/index.html avian/frontend/styles.css avian/frontend/apt.js
rg -n "SIMPLE_COLLAGE|renderSimpleCollage|oneHourFallback|detailAutoClose|touchend|static-head|staticTitle|nest-mark" avian/frontend
```

Tests present in the repository are Python tests (`tests/test_analysis.py` and `tests/test_apprise_notifications.py`) and do not obviously cover this frontend. A JavaScript syntax check and browser smoke test are more relevant before committing these changes.

## User/context limitations

- No persistent user memories were available to export.
- No identity, career, or general preference data is known.
- The only reliable project context is the local repository and the uncommitted diff summarized above.
- The user specifically linked `avian/frontend/styles.css`, so treat that file as central to the handoff.

