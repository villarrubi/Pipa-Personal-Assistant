#include "pipa_audio.h"

#include "board_pins.h"

namespace pipa {

namespace {
constexpr uint8_t kEs8311Address = 0x18;
constexpr uint8_t kEs7210Address = 0x40;
}  // namespace

bool PipaAudio::probeAddress(TwoWire& wire, uint8_t address) {
  wire.beginTransmission(address);
  return wire.endTransmission() == 0;
}

bool PipaAudio::begin(TwoWire& wire) {
  status_ = AudioProbeStatus{};
  if (!state_machine_.beginProbe()) {
    state_machine_.fail();
    status_.state = state_machine_.state();
    return false;
  }
#if PIPA_BOARD_REVISION == 2
  // Keep the power amplifier off until a real playback path is configured.
  pinMode(pipa::board::kAmplifierEnable, OUTPUT);
  digitalWrite(pipa::board::kAmplifierEnable, LOW);

  status_.output_codec_present = probeAddress(wire, kEs8311Address);
  status_.input_codec_present = probeAddress(wire, kEs7210Address);
  status_.amplifier_disabled = true;
  status_.state = state_machine_.state();
  return status_.output_codec_present || status_.input_codec_present;
#else
  // V1 uses PCM5101/NS8002 rather than the V2 I2C codecs. Do not touch GPIO2
  // or GPIO15 here: on V1 they are microphone clock signals, not audio
  // control pins. A real V1 audio path needs its own reviewed driver.
  (void)wire;
  state_machine_.fail();
  status_.state = state_machine_.state();
  return false;
#endif
}

}  // namespace pipa
