#pragma once

#include <Arduino.h>

namespace pipa {

/**
 * Conservative battery-voltage probe for the V2 board.
 *
 * The board exposes the divided battery voltage on its ADC. This class never
 * controls charging or power; it only publishes a bounded approximate
 * percentage when the selected board revision has a documented ADC pin.
 */
class PipaPower {
 public:
  bool begin();
  void update();
  int batteryPercent() const { return battery_percent_; }

 private:
  static constexpr uint16_t kMinimumMillivolts = 3000;
  static constexpr uint16_t kEmptyMillivolts = 3300;
  static constexpr uint16_t kFullMillivolts = 4200;
  static constexpr uint16_t kMaximumMillivolts = 4500;

  bool ready_ = false;
  int battery_percent_ = -1;
};

}  // namespace pipa
