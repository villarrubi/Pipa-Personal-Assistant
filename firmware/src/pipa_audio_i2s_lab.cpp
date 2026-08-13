#include "pipa_audio_i2s_lab.h"

#if defined(PIPA_AUDIO_I2S_LAB) && PIPA_AUDIO_I2S_LAB

#if defined(PIPA_SECURE_SESSION_ENABLED) && PIPA_SECURE_SESSION_ENABLED
#error "The audio I2S lab must never be combined with the production secure environment."
#endif

#include "board_pins.h"

namespace pipa {

bool PipaAudioI2sLab::begin() {
#if PIPA_BOARD_REVISION == 2
  // Keep the external amplifier off even while the I2S peripheral is probed.
  pinMode(board::kAmplifierEnable, OUTPUT);
  digitalWrite(board::kAmplifierEnable, LOW);
  status_.amplifier_disabled = true;

  // This mirrors the manufacturer's V2 wiring and uses a bounded, idle bus
  // configuration. No read/write call is made, so no audio leaves or enters
  // the device from this probe.
  i2s_.setPins(
      board::kI2sBclk,
      board::kI2sLrck,
      board::kI2sDataIn,
      board::kI2sMicData,
      board::kI2sMclk);
  status_.bus_ready = i2s_.begin(
      I2S_MODE_STD,
      24000,
      I2S_DATA_BIT_WIDTH_16BIT,
      I2S_SLOT_MODE_STEREO,
      I2S_STD_SLOT_BOTH);
  if (!status_.bus_ready) {
    i2s_.end();
  }
  return status_.bus_ready;
#else
  return false;
#endif
}

void PipaAudioI2sLab::end() {
  if (status_.bus_ready) {
    i2s_.end();
  }
  status_.bus_ready = false;
#if PIPA_BOARD_REVISION == 2
  pinMode(board::kAmplifierEnable, OUTPUT);
  digitalWrite(board::kAmplifierEnable, LOW);
#endif
  status_.amplifier_disabled = true;
}

}  // namespace pipa

#endif
