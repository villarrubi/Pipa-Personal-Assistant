#include "pipa_voice_activity.h"

#include <algorithm>

namespace pipa {

uint32_t PipaVoiceActivityDetector::integerSquareRoot(uint64_t value) {
  uint64_t result = 0;
  uint64_t bit = uint64_t{1} << 62;
  while (bit > value) bit >>= 2;
  while (bit != 0) {
    if (value >= result + bit) {
      value -= result + bit;
      result = (result >> 1) + bit;
    } else {
      result >>= 1;
    }
    bit >>= 2;
  }
  return static_cast<uint32_t>(result);
}

uint32_t PipaVoiceActivityDetector::rmsWithoutDc(
    const int16_t* samples,
    size_t sample_count) {
  if (samples == nullptr || sample_count == 0 || sample_count > 4096) return 0;
  int64_t sum = 0;
  for (size_t index = 0; index < sample_count; ++index) sum += samples[index];
  const int32_t mean = static_cast<int32_t>(sum / static_cast<int64_t>(sample_count));
  uint64_t squared_sum = 0;
  for (size_t index = 0; index < sample_count; ++index) {
    const int32_t centered = static_cast<int32_t>(samples[index]) - mean;
    squared_sum += static_cast<uint64_t>(static_cast<int64_t>(centered) * centered);
  }
  return integerSquareRoot(squared_sum / sample_count);
}

PipaVoiceActivityEvent PipaVoiceActivityDetector::process(
    const int16_t* samples,
    size_t sample_count) {
  last_rms_ = rmsWithoutDc(samples, sample_count);
  uint32_t threshold = std::max(kMinimumSpeechRms, noise_floor_rms_ * 3U);
  threshold = std::min(threshold, kMaximumAdaptiveThreshold);
  const bool voiced = last_rms_ >= threshold;

  if (!speech_active_) {
    if (voiced) {
      if (voiced_chunks_ < UINT8_MAX) ++voiced_chunks_;
      if (voiced_chunks_ >= kStartChunks) {
        speech_active_ = true;
        silent_chunks_ = 0;
        return PipaVoiceActivityEvent::kSpeechStarted;
      }
    } else {
      voiced_chunks_ = 0;
      // Slow adaptation follows fans and room noise without allowing one loud
      // transient to raise the threshold for the next real utterance.
      noise_floor_rms_ = (noise_floor_rms_ * 31U + last_rms_) / 32U;
    }
    return PipaVoiceActivityEvent::kSilence;
  }

  if (voiced) {
    silent_chunks_ = 0;
    return PipaVoiceActivityEvent::kSpeech;
  }
  if (silent_chunks_ < UINT8_MAX) ++silent_chunks_;
  if (silent_chunks_ >= kEndSilenceChunks) {
    speech_active_ = false;
    voiced_chunks_ = 0;
    silent_chunks_ = 0;
    return PipaVoiceActivityEvent::kSpeechEnded;
  }
  return PipaVoiceActivityEvent::kSpeech;
}

void PipaVoiceActivityDetector::resetUtterance() {
  voiced_chunks_ = 0;
  silent_chunks_ = 0;
  speech_active_ = false;
  last_rms_ = 0;
}

}  // namespace pipa
