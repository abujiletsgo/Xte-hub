# CrossPoint Firmware — Long-Press Chapter Navigation

## What This Changes

**Only the side buttons.** Everything else stays stock.

| Button | Short Press | Long Press (hold 1s) |
|--------|-------------|----------------------|
| Side Down | Next page (unchanged) | Jump to next chapter start |
| Side Up | Previous page (unchanged) | Jump to previous chapter start |
| OK | Stock behavior | Stock behavior |
| Back | Stock behavior | Stock behavior |

## Why

XteSync briefing EPUBs use one spine item per category (Tech, Economics, Politics...).
Each spine item starts with a summary page, followed by in-depth detail pages.

Long-press lets you skip between categories without paging through the detail.
Short-press is still normal page turn for reading within a category.

## How It Works

CrossPoint already tracks `currentSpineIndex` for EPUB navigation. The mod just
adds a hold-duration check on the side buttons:

- Hold ≥ 1 second → increment/decrement spine index, set page to 0, full refresh
- Release before 1 second → normal page turn (unchanged)

Full display refresh on chapter jump clears e-ink ghosting and gives tactile
feedback that you've made a "big jump" vs a normal page turn.

## EPUB Spine Mapping

```
spine[0] → Cover page
spine[1] → Tech (summary + detail pages)
spine[2] → Economics (summary + detail pages)
spine[3] → Politics (summary + detail pages)
...
```

The XteSync EPUB builder structures chapters this way automatically.
