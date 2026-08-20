#pragma once

#include <stddef.h>
#include <stdint.h>

namespace pipa {

// Offline, fail-closed gate for the hands-free microphone. PCM is evaluated
// on the ESP32 and discarded unless the configured activation phrase is
// recognized. No transport or persistent storage is owned by this class.
class PipaLocalWakePhrase {
 public:
  bool begin();
  bool process(const int16_t* samples, size_t sample_count);
  void reset();
  bool ready() const { return ready_; }

 private:
  struct Impl;
  Impl* impl_ = nullptr;
  bool ready_ = false;
};

}  // namespace pipa
