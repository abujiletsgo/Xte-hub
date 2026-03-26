/**
 * CrossPoint Firmware - EPUB Reader Navigation Mod for XteSync
 *
 * Modifications to EpubReaderActivity button handling:
 * - Side buttons: long-press = chapter jump (next/prev spine item)
 * - OK button: long-press = toggle bookmark
 * - Back button: long-press = jump to cover page
 *
 * Short-press behavior on all buttons is unchanged from stock.
 *
 * EPUB spine mapping (set by XteSync EPUB builder):
 *   spine[0] = Cover page
 *   spine[1+] = One category each (summary page + in-depth pages within)
 *
 * Long-press on side buttons always lands on page 0 of the target
 * spine item = summary page.
 */

#include "EpubReaderActivity.h"

static constexpr uint32_t LONG_PRESS_MS = 1000;

static bool longPressHandledNext = false;
static bool longPressHandledPrev = false;
static bool longPressHandledOk = false;
static bool longPressHandledBack = false;

void EpubReaderActivity::handleButtonInput() {
    // --- SIDE BUTTON DOWN (Next Page / Next Chapter) ---
    if (nextPageButton.isPressed()) {
        if (nextPageButton.holdDuration() >= LONG_PRESS_MS && !longPressHandledNext) {
            uint16_t next = currentSpineIndex + 1;
            if (next < epub->getSpineCount()) {
                currentSpineIndex = next;
                currentPageNumber = 0;
                loadCurrentSection();
                display->fullRefresh();
                updateProgressBar();
            }
            longPressHandledNext = true;
        }
    } else if (nextPageButton.wasReleased()) {
        if (!longPressHandledNext) {
            nextPage();
        }
        longPressHandledNext = false;
    }

    // --- SIDE BUTTON UP (Previous Page / Previous Chapter) ---
    if (prevPageButton.isPressed()) {
        if (prevPageButton.holdDuration() >= LONG_PRESS_MS && !longPressHandledPrev) {
            if (currentSpineIndex > 0) {
                currentSpineIndex--;
                currentPageNumber = 0;
                loadCurrentSection();
                display->fullRefresh();
                updateProgressBar();
            }
            longPressHandledPrev = true;
        }
    } else if (prevPageButton.wasReleased()) {
        if (!longPressHandledPrev) {
            prevPage();
        }
        longPressHandledPrev = false;
    }

    // --- OK BUTTON (Menu / Bookmark Toggle) ---
    if (okButton.isPressed()) {
        if (okButton.holdDuration() >= LONG_PRESS_MS && !longPressHandledOk) {
            toggleBookmark();
            longPressHandledOk = true;
        }
    } else if (okButton.wasReleased()) {
        if (!longPressHandledOk) {
            showReadingMenu();
        }
        longPressHandledOk = false;
    }

    // --- BACK BUTTON (Go Back / Jump to Cover) ---
    if (backButton.isPressed()) {
        if (backButton.holdDuration() >= LONG_PRESS_MS && !longPressHandledBack) {
            currentSpineIndex = 0;
            currentPageNumber = 0;
            loadCurrentSection();
            display->fullRefresh();
            updateProgressBar();
            longPressHandledBack = true;
        }
    } else if (backButton.wasReleased()) {
        if (!longPressHandledBack) {
            goBack();
        }
        longPressHandledBack = false;
    }
}

void EpubReaderActivity::toggleBookmark() {
    BookmarkKey key = {
        .spineIndex = currentSpineIndex,
        .pageNumber = currentPageNumber,
    };

    if (bookmarkManager->hasBookmark(key)) {
        bookmarkManager->removeBookmark(key);
        showToast("Bookmark removed");
    } else {
        bookmarkManager->addBookmark(key);
        showToast("Bookmarked!");
    }

    display->partialRefresh();
}

void EpubReaderActivity::updateProgressBar() {
    char buf[32];
    snprintf(buf, sizeof(buf), "%d / %d",
             currentSpineIndex, epub->getSpineCount() - 1);
    display->drawStatusText(buf, ALIGN_BOTTOM_CENTER);
}
