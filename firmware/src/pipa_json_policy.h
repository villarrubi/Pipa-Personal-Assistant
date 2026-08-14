#pragma once

#include <cstddef>

namespace pipa {

// JSON objects at the protocol boundary must not contain repeated keys.  The
// ArduinoJson parser keeps the last value, while the Core rejects ambiguous
// objects; keeping this check in a small transport-independent primitive
// makes both sides enforce the same rule.
bool isDuplicateFreeJson(const char* json, std::size_t length);

}  // namespace pipa
