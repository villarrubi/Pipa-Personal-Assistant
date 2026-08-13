#pragma once

// This header is intentionally empty in production builds. The class is only
// available in the opt-in audio-i2s-lab PlatformIO environment, which keeps
// the experimental I2S wiring out of the shipped firmware.
#if defined(PIPA_AUDIO_I2S_LAB) && PIPA_AUDIO_I2S_LAB

#include <Arduino.h>

#include "ESP_I2S.h"

namespace pipa {

struct AudioI2sLabStatus {
  bool bus_ready = false;
  bool amplifier_disabled = true;
};

/**
 * Compile-only, opt-in I2S wiring probe for the Waveshare V2 board.
 *
 * It configures the Arduino I2S bus but deliberately does not configure a
 * codec, enable the amplifier, read microphone samples, or write speaker
 * samples. It exists to catch SDK/pin/API drift before the physical board
 * arrives; it must not be treated as an audio capability.
 */
class PipaAudioI2sLab {
 public:
  bool begin();
  void end();
  bool ready() const { return status_.bus_ready; }
  const AudioI2sLabStatus& status() const { return status_; }

 private:
  I2SClass i2s_;
  AudioI2sLabStatus status_;
};

}  // namespace pipa

#endif
