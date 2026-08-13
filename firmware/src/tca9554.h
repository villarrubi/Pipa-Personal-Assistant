#pragma once

#include <Arduino.h>
#include <Wire.h>

namespace pipa {

class Tca9554 {
 public:
  static constexpr uint8_t kDefaultAddress = 0x20;
  static constexpr uint8_t kTouchReset = 1;
  static constexpr uint8_t kDisplayReset = 2;

  bool begin(TwoWire& wire, uint8_t address = kDefaultAddress);
  bool setOutput(uint8_t pin, bool high);

 private:
  bool writeRegister(uint8_t reg, uint8_t value);
  bool readRegister(uint8_t reg, uint8_t& value);

  TwoWire* wire_ = nullptr;
  uint8_t address_ = kDefaultAddress;
  uint8_t output_state_ = 0;
};

}  // namespace pipa
