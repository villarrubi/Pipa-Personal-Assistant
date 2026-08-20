#pragma once

#include <stddef.h>
#include <stdint.h>

namespace pipa {

enum class PipaVoiceActivityEvent : uint8_t {
  kSilence = 0,
  kSpeechStarted = 1,
  kSpeech = 2,
  kSpeechEnded = 3,
};

// Small, deterministic endpoint detector for the always-listening firmware.
// It does not recognize words and never persists audio. Its only job is to
// distinguish an utterance from the adaptive room noise floor so encrypted
// capture can start and finish without a touch or a fixed normal duration.
class PipaVoiceActivityDetector {
 public:
  static constexpr uint8_t kStartChunks = 2;
  static constexpr uint8_t kEndSilenceChunks = 7;
  static constexpr uint32_t kMinimumSpeechRms = 450;
  static constexpr uint32_t kMaximumAdaptiveThreshold = 6000;

  PipaVoiceActivityEvent process(const int16_t* samples, size_t sample_count);
  void resetUtterance();
  bool speechActive() const { return speech_active_; }
  uint32_t lastRms() const { return last_rms_; }
  uint32_t noiseFloorRms() const { return noise_floor_rms_; }

 private:
  static uint32_t rmsWithoutDc(const int16_t* samples, size_t sample_count);
  static uint32_t integerSquareRoot(uint64_t value);

  uint32_t noise_floor_rms_ = 120;
  uint32_t last_rms_ = 0;
  uint8_t voiced_chunks_ = 0;
  uint8_t silent_chunks_ = 0;
  bool speech_active_ = false;
};

}  // namespace pipa
