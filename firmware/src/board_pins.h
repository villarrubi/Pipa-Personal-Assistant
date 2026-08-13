#pragma once

#include <Arduino.h>

#if __has_include("pipa_device_config.local.h")
#include "pipa_device_config.local.h"
#else
#include "pipa_device_config.h"
#endif

// Pin map based on Waveshare's official 1.85C documentation and schematics.
// Keeping it in one place prevents a future display/audio driver from silently
// using the V1 wiring on a V2 board. V2 moved the I2C bus to GPIO10/11 and
// added ES8311/ES7210-specific audio control. V1 has no dedicated amplifier
// enable or MCLK pin; those entries intentionally use kNoPin.
namespace pipa::board {

constexpr uint8_t kNoPin = 0xFF;

#if PIPA_BOARD_REVISION == 2
constexpr uint8_t kI2cSda = 11;
constexpr uint8_t kI2cScl = 10;
constexpr uint8_t kBatteryAdc = 8;
constexpr uint8_t kTouchInterrupt = 4;
constexpr uint8_t kTouchResetExpander = 1;
constexpr uint8_t kDisplayResetExpander = 2;
constexpr uint8_t kDisplaySck = 40;
constexpr uint8_t kDisplayData0 = 46;
constexpr uint8_t kDisplayData1 = 45;
constexpr uint8_t kDisplayData2 = 42;
constexpr uint8_t kDisplayData3 = 41;
constexpr uint8_t kDisplayCs = 21;
constexpr uint8_t kDisplayTearingEffect = 18;
constexpr uint8_t kDisplayBacklight = 5;
constexpr uint8_t kAmplifierEnable = 15;
constexpr uint8_t kI2sMclk = 2;
constexpr uint8_t kI2sBclk = 48;
constexpr uint8_t kI2sLrck = 38;
constexpr uint8_t kI2sDataIn = 47;
constexpr uint8_t kI2sMicData = 39;
#elif PIPA_BOARD_REVISION == 1
constexpr uint8_t kI2cSda = 3;
constexpr uint8_t kI2cScl = 1;
constexpr uint8_t kBatteryAdc = kNoPin;
constexpr uint8_t kTouchInterrupt = 4;
constexpr uint8_t kTouchResetExpander = 1;
constexpr uint8_t kDisplayResetExpander = 2;
constexpr uint8_t kDisplaySck = 40;
constexpr uint8_t kDisplayData0 = 46;
constexpr uint8_t kDisplayData1 = 45;
constexpr uint8_t kDisplayData2 = 42;
constexpr uint8_t kDisplayData3 = 41;
constexpr uint8_t kDisplayCs = 21;
constexpr uint8_t kDisplayTearingEffect = 18;
constexpr uint8_t kDisplayBacklight = 5;
constexpr uint8_t kAmplifierEnable = kNoPin;
constexpr uint8_t kI2sMclk = kNoPin;
constexpr uint8_t kI2sBclk = 48;
constexpr uint8_t kI2sLrck = 38;
constexpr uint8_t kI2sDataIn = 47;
constexpr uint8_t kI2sMicData = 39;
#else
#error "PIPA_BOARD_REVISION must be 1 or 2"
#endif

}  // namespace pipa::board
