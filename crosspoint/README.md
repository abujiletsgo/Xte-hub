# CrossPoint Firmware — XteSync Navigation Mod

## Button Behavior

| Button | Short Press | Long Press (hold 1s) |
|--------|-------------|----------------------|
| Side Down | Next page (stock) | Jump to next chapter start |
| Side Up | Previous page (stock) | Jump to previous chapter start |
| OK | Reading menu (stock) | Toggle bookmark |
| Back | Go back (stock) | Jump to cover page |

Short-press on every button is unchanged from stock CrossPoint.

## How It Works

XteSync briefing EPUBs use one spine item per category (Tech, Economics, Politics...).
Each spine item starts with a summary page, followed by in-depth detail pages.

- **Long-press side buttons** — increment/decrement spine index, set page to 0, full refresh. Lands on summary page every time.
- **Long-press OK** — toggles bookmark on current page via existing `bookmarkManager`.
- **Long-press Back** — jumps to spine[0] (cover page).
- **Full refresh on chapter jump** — clears e-ink ghosting, gives clear feedback that you've jumped vs paged.
- **Progress indicator** — shows "2 / 6" at bottom after a chapter jump so you know where you are.

## EPUB Spine Mapping

```
spine[0] → Cover page
spine[1] → Tech (summary + detail pages)
spine[2] → Economics (summary + detail pages)
spine[3] → Politics (summary + detail pages)
...
```

The XteSync EPUB builder structures chapters this way automatically.
