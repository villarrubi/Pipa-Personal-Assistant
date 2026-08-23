// Capture initialization derived from Waveshare's ESP32-S3-Touch-LCD-1.85C
// V2 Arduino example and Espressif's ES7210 driver (Apache-2.0).

#include "pipa_es7210.h"

namespace pipa {
namespace {

constexpr uint8_t kAddress = 0x40;
// The original demo levels (36 dB analogue + 24 dB digital) leave almost no
// headroom for close speech. Once the ADC clips, Windows-side normalization
// cannot reconstruct the consonants Whisper needs. Keep enough analogue gain
// for the onboard microphones while reserving 12 dB of end-to-end headroom.
constexpr uint8_t kAnalogueGain30Db = 0x1A;
constexpr uint8_t kDigitalGain18Db = 0xE3;

struct RegisterValue {
  uint8_t address;
  uint8_t value;
};

// 16 kHz, 16-bit standard I2S, MCLK = 256 * Fs (4.096 MHz), 2.87 V
// microphone bias, 30 dB analogue gain and +18 dB digital gain. Both hardware
// microphone channels are enabled; ESP_I2S downmixes their stereo stream to
// mono before transport.
constexpr RegisterValue kCaptureConfiguration[] = {
    {0x00, 0xFF}, {0x00, 0x32},
    {0x09, 0x30}, {0x0A, 0x30},
    {0x23, 0x2A}, {0x22, 0x0A}, {0x21, 0x2A}, {0x20, 0x0A},
    {0x11, 0x60}, {0x12, 0x00},
    {0x40, 0xC3},
    {0x41, 0x70}, {0x42, 0x70},
    {0x43, kAnalogueGain30Db}, {0x44, kAnalogueGain30Db},
    {0x45, kAnalogueGain30Db}, {0x46, kAnalogueGain30Db},
    {0x47, 0x08}, {0x48, 0x08}, {0x49, 0x08}, {0x4A, 0x08},
    {0x07, 0x20}, {0x02, 0xC1}, {0x04, 0x01}, {0x05, 0x00},
    {0x06, 0x04}, {0x4B, 0x0F}, {0x4C, 0x0F},
    {0x00, 0x71}, {0x00, 0x41},
    {0x1B, kDigitalGain18Db}, {0x1C, kDigitalGain18Db},
    {0x1D, kDigitalGain18Db}, {0x1E, kDigitalGain18Db},
};

}  // namespace

bool PipaEs7210::writeRegister(uint8_t address, uint8_t value) {
  if (wire_ == nullptr) return false;
  wire_->beginTransmission(kAddress);
  wire_->write(address);
  wire_->write(value);
  return wire_->endTransmission(true) == 0;
}

bool PipaEs7210::begin(TwoWire& wire) {
  end();
  wire_ = &wire;
  for (const RegisterValue& item : kCaptureConfiguration) {
    if (!writeRegister(item.address, item.value)) {
      end();
      return false;
    }
  }
  ready_ = true;
  return true;
}

void PipaEs7210::end() {
  if (wire_ != nullptr && ready_) {
    // Best-effort software reset/power-down. A failed I2C write still leaves
    // the software gate closed and the amplifier controlled separately.
    writeRegister(0x00, 0xFF);
  }
  ready_ = false;
  wire_ = nullptr;
}

}  // namespace pipa
