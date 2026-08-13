#pragma once

#include <stddef.h>

#include <string>

namespace pipa::display_text {

constexpr size_t kMaxSummaryBytes = 96;
constexpr size_t kMaxLineCharacters = 23;

// Convert the small set of expected Spanish UTF-8 characters to the ASCII
// glyph set used by the display. Unknown non-ASCII code points become '?'
// instead of being passed to the font lookup as raw bytes.
std::string normalizeSummary(const char* text);

// Split a normalized summary into the two physical lines used by the UI.
// Neither output exceeds kMaxLineCharacters.
void splitSummary(const char* text, std::string& first, std::string& second);

}  // namespace pipa::display_text
