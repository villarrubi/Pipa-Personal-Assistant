#pragma once

#include <Arduino.h>
#include <Wire.h>

namespace pipa {

struct AudioProbeStatus {
  bool output_codec_present = false;
  bool input_codec_present = false;
  bool amplifier_disabled = true;
};

/**
 * Board-level audio probe.
 *
 * It deliberately does not write codec registers, enable the amplifier, or
 * capture microphone data. It only verifies the I2C addresses documented by
 * Waveshare so the real I2S/codec driver can be enabled after physical review.
 */
class PipaAudio {
 public:
  bool begin(TwoWire& wire);
  const AudioProbeStatus& status() const { return status_; }

 private:
  static bool probeAddress(TwoWire& wire, uint8_t address);

  AudioProbeStatus status_;
};

}  // namespace pipa
