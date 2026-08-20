#pragma once

#include <Arduino.h>
#include <Wire.h>

namespace pipa {

// Minimal capture-only ES7210 setup for the Waveshare V2 board. The register
// sequence follows Waveshare's Apache-2.0 Arduino example; speaker playback
// and the external power amplifier are intentionally outside this driver.
class PipaEs7210 {
 public:
  bool begin(TwoWire& wire);
  void end();
  bool ready() const { return ready_; }

 private:
  bool writeRegister(uint8_t address, uint8_t value);

  TwoWire* wire_ = nullptr;
  bool ready_ = false;
};

}  // namespace pipa
