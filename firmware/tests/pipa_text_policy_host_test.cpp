#include <cassert>

#include "pipa_text_policy.h"

int main() {
  using pipa::isSafeDisplayText;
  using pipa::isSafeGesture;
  using pipa::isSafeTextSource;

  assert(isSafeGesture("tap"));
  assert(isSafeGesture("double_tap"));
  assert(isSafeGesture("swipe_left"));
  assert(isSafeGesture("swipe_right"));
  assert(!isSafeGesture(nullptr));
  assert(!isSafeGesture("call"));

  assert(isSafeTextSource("voice"));
  assert(isSafeTextSource("touch"));
  assert(isSafeTextSource("mobile"));
  assert(isSafeTextSource("debug"));
  assert(isSafeTextSource("unknown"));
  assert(!isSafeTextSource(nullptr));
  assert(!isSafeTextSource("shell"));

  assert(isSafeDisplayText("Confirmar accion", 64));
  assert(!isSafeDisplayText(nullptr, 64));
  assert(!isSafeDisplayText("", 64));
  assert(!isSafeDisplayText("line\nbreak", 64));
  assert(!isSafeDisplayText("too long", 3));

  const char malformed_utf8[] = "\xC0\x80";
  const char bidi_override[] = "\xE2\x80\xAE";
  const char zero_width_space[] = "\xE2\x80\x8B";
  assert(!isSafeDisplayText(malformed_utf8, sizeof(malformed_utf8) - 1));
  assert(!isSafeDisplayText(bidi_override, sizeof(bidi_override) - 1));
  assert(!isSafeDisplayText(zero_width_space, sizeof(zero_width_space) - 1));

  return 0;
}
