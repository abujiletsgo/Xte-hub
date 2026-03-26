/**
 * CrossPoint Firmware - Long-Press Chapter Navigation for XteSync EPUBs
 *
 * Minimal modification to EpubReaderActivity button handling.
 * Only changes: side buttons gain long-press → chapter jump.
 * All other buttons (OK, Back) remain stock behavior.
 *
 * EPUB spine mapping (set by XteSync EPUB builder):
 *   spine[0] = Cover page
 *   spine[1+] = One category each (summary page + in-depth pages within)
 *
 * Long-press always lands on page 0 of the target spine item = summary page.
 * Short-press behavior is completely unchanged.
 */

#include "EpubReaderActivity.h"

// How long you hold before it counts as a chapter jump
static constexpr uint32_t LONG_PRESS_MS = 1000;

// Per-button flag so the release doesn't also fire a short-press
static bool longPressHandledNext = false;
static bool longPressHandledPrev = false;

void EpubReaderActivity::handleButtonInput() {
    // --- SIDE BUTTON DOWN (Next) ---
    if (nextPageButton.isPressed()) {
        if (nextPageButton.holdDuration() >= LONG_PRESS_MS && !longPressHandledNext) {
            // Long-press: jump to next spine item (next category)
            uint16_t next = currentSpineIndex + 1;
            if (next < epub->getSpineCount()) {
                currentSpineIndex = next;
                currentPageNumber = 0;
                loadCurrentSection();
                display->fullRefresh();  // full refresh = clear ghosting, signals "big jump"
            }
            longPressHandledNext = true;
        }
    } else if (nextPageButton.wasReleased()) {
        if (!longPressHandledNext) {
            nextPage();  // unchanged short-press behavior
        }
        longPressHandledNext = false;
    }

    // --- SIDE BUTTON UP (Previous) ---
    if (prevPageButton.isPressed()) {
        if (prevPageButton.holdDuration() >= LONG_PRESS_MS && !longPressHandledPrev) {
            // Long-press: jump to previous spine item (previous category)
            if (currentSpineIndex > 0) {
                currentSpineIndex--;
                currentPageNumber = 0;
                loadCurrentSection();
                display->fullRefresh();
            }
            longPressHandledPrev = true;
        }
    } else if (prevPageButton.wasReleased()) {
        if (!longPressHandledPrev) {
            prevPage();  // unchanged short-press behavior
        }
        longPressHandledPrev = false;
    }

    // OK button, Back button: no changes, handled by stock code
}
