#pragma once

#include <Arduino.h>
#include <Wire.h>

#include "tca9554.h"

namespace pipa {

struct TouchPoint {
  uint16_t x = 0;
  uint16_t y = 0;
};

class Cst816Touch {
 public:
  bool begin(
      TwoWire& wire,
      uint8_t address = 0x15,
      Tca9554* io_expander = nullptr,
      uint8_t reset_expander_pin = Tca9554::kTouchReset,
      uint8_t interrupt_pin = 255);
  bool read(TouchPoint& point);

 private:
  TwoWire* wire_ = nullptr;
  Tca9554* io_expander_ = nullptr;
  uint8_t address_ = 0x15;
  uint8_t reset_expander_pin_ = Tca9554::kTouchReset;
  uint8_t interrupt_pin_ = 255;
};

}  // namespace pipa
