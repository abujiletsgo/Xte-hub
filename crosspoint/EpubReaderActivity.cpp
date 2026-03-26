/**
 * CrossPoint Firmware - EPUB Reader Navigation Mod for XteSync
 *
 * This file contains the modified button handling for the CrossPoint e-ink
 * reader to support XteSync's three-layer reading experience.
 *
 * Key modification: Long-press on page-turn buttons triggers chapter jump
 * instead of page turn, enabling quick navigation between briefing categories.
 *
 * EPUB Structure Assumption:
 *   spine[0] = Cover page
 *   spine[1] = Category 1 (summary page + in-depth pages)
 *   spine[2] = Category 2 (summary page + in-depth pages)
 *   ...
 *   Long-press always lands on page 0 of the spine item (= summary page)
 */

#include "EpubReaderActivity.h"
#include "EpubParser.h"
#include "Display.h"
#include "Button.h"

// Navigation thresholds
static constexpr uint32_t LONG_PRESS_THRESHOLD_MS = 1000;  // 1 second for chapter jump
static constexpr uint32_t DEBOUNCE_MS = 50;

// Button state tracking
static bool longPressHandledNext = false;
static bool longPressHandledPrev = false;
static bool longPressHandledOk = false;
static bool longPressHandledBack = false;

void EpubReaderActivity::loop() {
    // ... existing render/update code ...

    // === NEXT PAGE / NEXT CHAPTER (Side Button Down) ===
    if (nextPageButton.isPressed()) {
        if (nextPageButton.holdDuration() >= LONG_PRESS_THRESHOLD_MS) {
            if (!longPressHandledNext) {
                jumpToNextChapter();
                longPressHandledNext = true;
            }
        }
    } else {
        if (nextPageButton.wasReleased()) {
            if (!longPressHandledNext) {
                nextPage();  // Normal short-press page turn
            }
            longPressHandledNext = false;
        }
    }

    // === PREVIOUS PAGE / PREVIOUS CHAPTER (Side Button Up) ===
    if (prevPageButton.isPressed()) {
        if (prevPageButton.holdDuration() >= LONG_PRESS_THRESHOLD_MS) {
            if (!longPressHandledPrev) {
                jumpToPrevChapter();
                longPressHandledPrev = true;
            }
        }
    } else {
        if (prevPageButton.wasReleased()) {
            if (!longPressHandledPrev) {
                prevPage();  // Normal short-press page turn
            }
            longPressHandledPrev = false;
        }
    }

    // === OK BUTTON: Menu / Bookmark Toggle ===
    if (okButton.isPressed()) {
        if (okButton.holdDuration() >= LONG_PRESS_THRESHOLD_MS) {
            if (!longPressHandledOk) {
                toggleBookmark();
                longPressHandledOk = true;
            }
        }
    } else {
        if (okButton.wasReleased()) {
            if (!longPressHandledOk) {
                showReadingMenu();  // Normal short-press
            }
            longPressHandledOk = false;
        }
    }

    // === BACK BUTTON: Go Back / Jump to Cover ===
    if (backButton.isPressed()) {
        if (backButton.holdDuration() >= LONG_PRESS_THRESHOLD_MS) {
            if (!longPressHandledBack) {
                jumpToCover();
                longPressHandledBack = true;
            }
        }
    } else {
        if (backButton.wasReleased()) {
            if (!longPressHandledBack) {
                goBack();  // Normal short-press: back to folder
            }
            longPressHandledBack = false;
        }
    }
}

void EpubReaderActivity::jumpToNextChapter() {
    // CrossPoint already tracks spine index for EPUB navigation
    uint16_t nextSpine = currentSpineIndex + 1;
    if (nextSpine < epub->getSpineCount()) {
        currentSpineIndex = nextSpine;
        currentPageNumber = 0;  // Start of chapter = summary page
        loadCurrentSection();

        // Force full display refresh as visual signal for "big jump"
        // Full refresh clears ghosting and provides clear feedback
        display->fullRefresh();

        // Update progress indicator
        updateProgressBar();
    }
    // If at last chapter, do nothing (no wrap-around)
}

void EpubReaderActivity::jumpToPrevChapter() {
    if (currentSpineIndex > 0) {
        currentSpineIndex--;
        currentPageNumber = 0;  // Always land on summary page
        loadCurrentSection();
        display->fullRefresh();
        updateProgressBar();
    }
    // If at first chapter, do nothing
}

void EpubReaderActivity::jumpToCover() {
    // Jump to spine item 0 (cover page)
    currentSpineIndex = 0;
    currentPageNumber = 0;
    loadCurrentSection();
    display->fullRefresh();
    updateProgressBar();
}

void EpubReaderActivity::toggleBookmark() {
    // Toggle bookmark on current page
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

    // Brief display feedback
    display->partialRefresh();
}

void EpubReaderActivity::updateProgressBar() {
    // Show chapter X of Y indicator at bottom of screen
    char buf[32];
    snprintf(buf, sizeof(buf), "%d / %d",
             currentSpineIndex, epub->getSpineCount() - 1);
    display->drawStatusText(buf, ALIGN_BOTTOM_CENTER);
}
