# CrossPoint Firmware Navigation Mod

## Overview

Firmware modifications for the CrossPoint e-ink reader to support XteSync's
three-layer reading experience with long-press chapter navigation.

## Button Behavior

### Modified Controls

| Button | Short Press (<1s) | Long Press (≥1s) |
|--------|-------------------|-------------------|
| Side Up | Previous page | Previous chapter (lands on summary) |
| Side Down | Next page | Next chapter (lands on summary) |
| OK | Reading menu | Toggle bookmark/star |
| Back | Go to folder | Jump to cover page |

### Key Principle

Long-press always lands on a SUMMARY page (the first page of each chapter/spine item).
This maps to the EPUB structure where each spine item = one category.

## EPUB Spine Mapping

```
spine item 0 → Cover page
spine item 1 → Tech summary + Tech in-depth pages
spine item 2 → Economics summary + Economics in-depth pages
spine item 3 → Politics summary + Politics in-depth pages
...
```

## Implementation Notes

The chapter-jump leverages CrossPoint's existing EPUB spine navigation.
See `EpubReaderActivity.cpp` for the reference implementation.
