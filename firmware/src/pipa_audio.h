#pragma once

#include <Arduino.h>
#include <Wire.h>

#if __has_include("pipa_device_config.local.h")
#include "pipa_device_config.local.h"
#else
#include "pipa_device_config.h"
#endif
#include "pipa_audio_state.h"

#if PIPA_AUDIO_CAPTURE_ENABLED
#include "ESP_I2S.h"
#include "pipa_es7210.h"
#endif

namespace pipa {

struct AudioProbeStatus {
  bool output_codec_present = false;
  bool input_codec_present = false;
  bool amplifier_disabled = true;
  PipaAudioState state = PipaAudioState::kDisabled;
};

/**
 * Board-level audio probe and opt-in V2 microphone capture.
 *
 * Normal builds only probe documented I2C addresses. PIPA_AUDIO_CAPTURE_ENABLED
 * adds ES7210/I2S input while leaving the power amplifier disabled.
 */
class PipaAudio {
 public:
  bool begin(TwoWire& wire);
  bool beginCapture(bool display_ready, bool consented, bool secure_transport_ready);
  size_t readMonoPcm(uint8_t* output, size_t output_capacity);
  bool finishCapture();
  void cancelCapture();
  const AudioProbeStatus& status() const { return status_; }
  PipaAudioStateMachine& stateMachine() { return state_machine_; }
  const PipaAudioStateMachine& stateMachine() const { return state_machine_; }

 private:
  static bool probeAddress(TwoWire& wire, uint8_t address);

  AudioProbeStatus status_;
  PipaAudioStateMachine state_machine_;
#if PIPA_AUDIO_CAPTURE_ENABLED
  PipaEs7210 input_codec_;
  I2SClass i2s_;
  bool i2s_ready_ = false;
#endif
};

}  // namespace pipa
