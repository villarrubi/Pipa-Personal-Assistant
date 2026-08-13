#pragma once

#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace pipa {

// Validate text before it reaches the small device display. Besides the
// protocol's C0 controls, reject malformed UTF-8 and formatting code points
// that can make a confirmation look different from its signed meaning.
inline bool isSafeDisplayText(const char* text, size_t max_bytes) {
  if (text == nullptr) return false;
  const size_t length = strlen(text);
  if (length == 0 || length > max_bytes) return false;

  const auto continuation = [](uint8_t value) { return value >= 0x80 && value <= 0xBF; };
  for (size_t index = 0; index < length;) {
    const uint8_t first = static_cast<uint8_t>(text[index]);
    uint32_t code_point = 0;
    size_t width = 0;

    if (first <= 0x7F) {
      code_point = first;
      width = 1;
    } else if (first >= 0xC2 && first <= 0xDF) {
      if (index + 1 >= length || !continuation(static_cast<uint8_t>(text[index + 1]))) return false;
      code_point = (static_cast<uint32_t>(first & 0x1F) << 6) |
                   (static_cast<uint32_t>(static_cast<uint8_t>(text[index + 1])) & 0x3F);
      width = 2;
    } else if (first >= 0xE0 && first <= 0xEF) {
      if (index + 2 >= length) return false;
      const uint8_t second = static_cast<uint8_t>(text[index + 1]);
      const uint8_t third = static_cast<uint8_t>(text[index + 2]);
      if (!continuation(third) ||
          (first == 0xE0 ? second < 0xA0 || second > 0xBF
                         : first == 0xED ? second < 0x80 || second > 0x9F
                                         : !continuation(second))) {
        return false;
      }
      code_point = (static_cast<uint32_t>(first & 0x0F) << 12) |
                   (static_cast<uint32_t>(second & 0x3F) << 6) | (third & 0x3F);
      width = 3;
    } else if (first >= 0xF0 && first <= 0xF4) {
      if (index + 3 >= length) return false;
      const uint8_t second = static_cast<uint8_t>(text[index + 1]);
      const uint8_t third = static_cast<uint8_t>(text[index + 2]);
      const uint8_t fourth = static_cast<uint8_t>(text[index + 3]);
      if (!continuation(third) || !continuation(fourth) ||
          (first == 0xF0 ? second < 0x90 || second > 0xBF
                         : first == 0xF4 ? second < 0x80 || second > 0x8F
                                         : !continuation(second))) {
        return false;
      }
      code_point = (static_cast<uint32_t>(first & 0x07) << 18) |
                   (static_cast<uint32_t>(second & 0x3F) << 12) |
                   (static_cast<uint32_t>(third & 0x3F) << 6) | (fourth & 0x3F);
      width = 4;
    } else {
      return false;
    }

    const bool c0_or_c1_control = code_point < 0x20 ||
                                  (code_point >= 0x7F && code_point <= 0x9F);
    const bool formatting_control =
        (code_point >= 0x200B && code_point <= 0x200F) ||
        (code_point >= 0x202A && code_point <= 0x202E) ||
        (code_point >= 0x2060 && code_point <= 0x2069) || code_point == 0xFEFF;
    if (c0_or_c1_control || formatting_control) return false;
    index += width;
  }
  return true;
}

// Keep the firmware's producer contract aligned with the Core parser. A
// printable but unknown source is still protocol-invalid and must not be
// emitted just because it fits the display policy.
inline bool isSafeTextSource(const char* source) {
  if (source == nullptr) return false;
  return strcmp(source, "voice") == 0 || strcmp(source, "touch") == 0 ||
      strcmp(source, "mobile") == 0 || strcmp(source, "debug") == 0 ||
      strcmp(source, "unknown") == 0;
}

}  // namespace pipa
