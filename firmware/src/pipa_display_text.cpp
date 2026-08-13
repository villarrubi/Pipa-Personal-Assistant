#include "pipa_display_text.h"

#include <algorithm>
#include <cctype>

namespace pipa::display_text {
namespace {

char mappedUtf8(const unsigned char* bytes, size_t remaining, size_t& consumed) {
  if (remaining == 0) {
    consumed = 1;
    return '?';
  }

  const unsigned char lead = bytes[0];
  size_t expected = 1;
  if (lead >= 0xC2 && lead <= 0xDF) {
    expected = 2;
  } else if (lead >= 0xE0 && lead <= 0xEF) {
    expected = 3;
  } else if (lead >= 0xF0 && lead <= 0xF4) {
    expected = 4;
  }
  if (expected == 1 || remaining < expected) {
    consumed = 1;
    return '?';
  }

  for (size_t index = 1; index < expected; ++index) {
    if ((bytes[index] & 0xC0) != 0x80) {
      consumed = 1;
      return '?';
    }
  }

  // Reject overlong encodings, UTF-16 surrogate code points and values past
  // Unicode's upper bound while still consuming a valid unknown code point
  // as one display glyph.
  if ((lead == 0xE0 && bytes[1] < 0xA0) ||
      (lead == 0xED && bytes[1] >= 0xA0) ||
      (lead == 0xF0 && bytes[1] < 0x90) ||
      (lead == 0xF4 && bytes[1] >= 0x90)) {
    consumed = 1;
    return '?';
  }

  consumed = expected;
  if (expected != 2 || lead != 0xC3) return '?';
  switch (bytes[1]) {
    case 0x81:
      return 'A';
    case 0x89:
      return 'E';
    case 0x8D:
      return 'I';
    case 0x93:
      return 'O';
    case 0x9A:
      return 'U';
    case 0x91:
      return 'N';
    case 0x9C:
      return 'U';
    case 0xA1:
      return 'A';
    case 0xA9:
      return 'E';
    case 0xAD:
      return 'I';
    case 0xB3:
      return 'O';
    case 0xBA:
      return 'U';
    case 0xB1:
      return 'N';
    case 0xBC:
      return 'U';
    default:
      return '?';
  }
}

void appendBounded(std::string& result, char character) {
  if (result.size() < kMaxSummaryBytes) result.push_back(character);
}

}  // namespace

std::string normalizeSummary(const char* text) {
  std::string result;
  if (text == nullptr) return result;
  const size_t input_length = std::char_traits<char>::length(text);
  result.reserve(std::min(kMaxSummaryBytes, input_length));

  const auto* bytes = reinterpret_cast<const unsigned char*>(text);
  for (size_t index = 0; index < input_length && result.size() < kMaxSummaryBytes;) {
    const unsigned char value = bytes[index];
    if (value < 0x80) {
      ++index;
      if (value == '\r' || value == '\n') {
        appendBounded(result, ' ');
      } else if (value >= 0x20 && value <= 0x7E) {
        appendBounded(result, static_cast<char>(std::toupper(value)));
      } else {
        appendBounded(result, '?');
      }
      continue;
    }

    size_t consumed = 1;
    const char mapped = mappedUtf8(bytes + index, input_length - index, consumed);
    index += consumed;
    appendBounded(result, mapped);
  }

  const auto first = result.find_first_not_of(' ');
  if (first == std::string::npos) return {};
  const auto last = result.find_last_not_of(' ');
  return result.substr(first, last - first + 1);
}

void splitSummary(const char* text, std::string& first, std::string& second) {
  first.clear();
  second.clear();
  if (text == nullptr) return;

  const std::string summary(text);
  if (summary.size() <= kMaxLineCharacters) {
    first = summary;
    return;
  }

  size_t split = summary.rfind(' ', kMaxLineCharacters);
  if (split == std::string::npos || split == 0) split = kMaxLineCharacters;
  first = summary.substr(0, split);
  second = summary.substr(split);
  const auto first_non_space = second.find_first_not_of(' ');
  if (first_non_space == std::string::npos) {
    second.clear();
  } else {
    second.erase(0, first_non_space);
  }
  if (second.size() > kMaxLineCharacters) second.resize(kMaxLineCharacters);
}

}  // namespace pipa::display_text
