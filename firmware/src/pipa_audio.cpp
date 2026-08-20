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
  if (!status_.output_codec_present && !status_.input_codec_present) {
    // A missing codec is a failed physical initialization, not a usable
    // probe state. Keep the amplifier off and require a fresh probe before
    // any future audio path can be considered again.
    state_machine_.fail();
  }
#if PIPA_AUDIO_CAPTURE_ENABLED
  bool capture_ready = false;
  if (status_.input_codec_present && input_codec_.begin(wire)) {
    i2s_.setPins(
        board::kI2sBclk,
        board::kI2sLrck,
        board::kI2sDataIn,
        board::kI2sMicData,
        board::kI2sMclk);
    i2s_.setTimeout(250);
    i2s_ready_ = i2s_.begin(
        I2S_MODE_STD,
        16000,
        I2S_DATA_BIT_WIDTH_16BIT,
        I2S_SLOT_MODE_STEREO,
        I2S_STD_SLOT_BOTH) &&
        i2s_.configureRX(
            16000,
            I2S_DATA_BIT_WIDTH_16BIT,
            I2S_SLOT_MODE_STEREO,
            I2S_RX_TRANSFORM_16_STEREO_TO_MONO);
    capture_ready = i2s_ready_;
  }
  if (!capture_ready) {
    if (i2s_ready_) i2s_.end();
    i2s_ready_ = false;
    input_codec_.end();
  }
  state_machine_.markCodecReady(capture_ready);
#endif
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

bool PipaAudio::beginCapture(
    bool display_ready,
    bool consented,
    bool secure_transport_ready) {
#if PIPA_AUDIO_CAPTURE_ENABLED
  return i2s_ready_ && input_codec_.ready() &&
      state_machine_.beginListening(display_ready, consented, secure_transport_ready);
#else
  (void)display_ready;
  (void)consented;
  (void)secure_transport_ready;
  return false;
#endif
}

size_t PipaAudio::readMonoPcm(uint8_t* output, size_t output_capacity) {
#if PIPA_AUDIO_CAPTURE_ENABLED
  if (!state_machine_.canCapture() || output == nullptr || output_capacity == 0 ||
      output_capacity > 4096 || output_capacity % 2 != 0) {
    return 0;
  }
  const size_t read = i2s_.readBytes(reinterpret_cast<char*>(output), output_capacity);
  return read > output_capacity || read % 2 != 0 ? 0 : read;
#else
  (void)output;
  (void)output_capacity;
  return 0;
#endif
}

bool PipaAudio::finishCapture() {
  return state_machine_.beginDraining() && state_machine_.finishDraining();
}

void PipaAudio::cancelCapture() {
  if (state_machine_.state() == PipaAudioState::kListening) {
    if (!finishCapture()) state_machine_.fail();
  }
}

}  // namespace pipa
