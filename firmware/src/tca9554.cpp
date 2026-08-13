#include "tca9554.h"

namespace pipa {

namespace {
constexpr uint8_t kOutputRegister = 0x01;
constexpr uint8_t kConfigRegister = 0x03;
constexpr uint8_t kPinCount = 8;
}  // namespace

bool Tca9554::begin(TwoWire& wire, uint8_t address) {
  wire_ = &wire;
  address_ = address;
  if (!writeRegister(kConfigRegister, 0x00)) return false;

  uint8_t output = 0;
  if (!readRegister(kOutputRegister, output)) return false;
  output_state_ = output;
  return true;
}

bool Tca9554::setOutput(uint8_t pin, bool high) {
  if (wire_ == nullptr || pin == 0 || pin > kPinCount) return false;
  const uint8_t mask = static_cast<uint8_t>(1U << (pin - 1));
  if (high) {
    output_state_ = static_cast<uint8_t>(output_state_ | mask);
  } else {
    output_state_ = static_cast<uint8_t>(output_state_ & static_cast<uint8_t>(~mask));
  }
  return writeRegister(kOutputRegister, output_state_);
}

bool Tca9554::writeRegister(uint8_t reg, uint8_t value) {
  if (wire_ == nullptr) return false;
  wire_->beginTransmission(address_);
  wire_->write(reg);
  wire_->write(value);
  return wire_->endTransmission() == 0;
}

bool Tca9554::readRegister(uint8_t reg, uint8_t& value) {
  if (wire_ == nullptr) return false;
  wire_->beginTransmission(address_);
  wire_->write(reg);
  if (wire_->endTransmission(false) != 0 || wire_->requestFrom(address_, static_cast<uint8_t>(1)) != 1) {
    return false;
  }
  value = static_cast<uint8_t>(wire_->read());
  return true;
}

}  // namespace pipa
