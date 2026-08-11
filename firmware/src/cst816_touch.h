#pragma once

#include <Arduino.h>
#include <Wire.h>

namespace pipa {

struct TouchPoint {
  uint16_t x = 0;
  uint16_t y = 0;
};

class Cst816Touch {
 public:
  bool begin(TwoWire& wire, uint8_t address = 0x15);
  bool read(TouchPoint& point);

 private:
  TwoWire* wire_ = nullptr;
  uint8_t address_ = 0x15;
};

}  // namespace pipa
