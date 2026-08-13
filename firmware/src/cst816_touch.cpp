#include "cst816_touch.h"

namespace pipa {

bool Cst816Touch::begin(
    TwoWire& wire,
    uint8_t address,
    Tca9554* io_expander,
    uint8_t reset_expander_pin,
    uint8_t interrupt_pin) {
  wire_ = &wire;
  io_expander_ = io_expander;
  address_ = address;
  reset_expander_pin_ = reset_expander_pin;
  interrupt_pin_ = interrupt_pin;
  if (io_expander_ != nullptr && !io_expander_->setOutput(reset_expander_pin_, false)) return false;
  delay(10);
  if (io_expander_ != nullptr && !io_expander_->setOutput(reset_expander_pin_, true)) return false;
  delay(50);
  if (interrupt_pin_ != 255) pinMode(interrupt_pin_, INPUT_PULLUP);
  wire_->beginTransmission(address_);
  wire_->write(0x00);
  return wire_->endTransmission() == 0;
}

bool Cst816Touch::read(TouchPoint& point) {
  if (wire_ == nullptr) return false;
  if (interrupt_pin_ != 255 && digitalRead(interrupt_pin_) != LOW) return false;
  wire_->beginTransmission(address_);
  wire_->write(0x02);
  if (wire_->endTransmission(false) != 0 || wire_->requestFrom(address_, static_cast<uint8_t>(5)) != 5) {
    return false;
  }
  const uint8_t fingers = wire_->read();
  const uint8_t x_high = wire_->read();
  const uint8_t x_low = wire_->read();
  const uint8_t y_high = wire_->read();
  const uint8_t y_low = wire_->read();
  if (fingers == 0) return false;

  point.x = static_cast<uint16_t>(((x_high & 0x0F) << 8) | x_low);
  point.y = static_cast<uint16_t>(((y_high & 0x0F) << 8) | y_low);
  return true;
}

}  // namespace pipa
