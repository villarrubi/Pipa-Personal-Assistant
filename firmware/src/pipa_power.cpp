#include "pipa_power.h"

#include "board_pins.h"

namespace pipa {

bool PipaPower::begin() {
  if (pipa::board::kBatteryAdc == pipa::board::kNoPin) return false;
  analogReadResolution(12);
  pinMode(pipa::board::kBatteryAdc, INPUT);
  ready_ = true;
  update();
  return true;
}

void PipaPower::update() {
  if (!ready_) return;

  // Waveshare's divider is 1:3 in the official example. Reject impossible or
  // disconnected readings rather than presenting a misleading percentage.
  const uint32_t sensed_millivolts = analogReadMilliVolts(pipa::board::kBatteryAdc);
  const uint32_t battery_millivolts = sensed_millivolts * 3U;
  if (battery_millivolts < kMinimumMillivolts || battery_millivolts > kMaximumMillivolts) {
    battery_percent_ = -1;
    return;
  }

  if (battery_millivolts <= kEmptyMillivolts) {
    battery_percent_ = 0;
  } else if (battery_millivolts >= kFullMillivolts) {
    battery_percent_ = 100;
  } else {
    battery_percent_ = static_cast<int>(
        (battery_millivolts - kEmptyMillivolts) * 100U /
        (kFullMillivolts - kEmptyMillivolts));
  }
}

}  // namespace pipa
