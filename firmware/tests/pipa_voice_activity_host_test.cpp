#include "pipa_voice_activity.h"

#include <array>
#include <cassert>
#include <cstdint>

namespace {

std::array<int16_t, 2048> alternating(int16_t amplitude) {
  std::array<int16_t, 2048> samples{};
  for (size_t index = 0; index < samples.size(); ++index) {
    samples[index] = index % 2 == 0 ? amplitude : static_cast<int16_t>(-amplitude);
  }
  return samples;
}

}  // namespace

int main() {
  pipa::PipaVoiceActivityDetector detector;
  const auto quiet = alternating(100);
  const auto voice = alternating(3000);

  for (uint8_t index = 0; index < pipa::PipaVoiceActivityDetector::kCalibrationChunks; ++index) {
    assert(detector.process(quiet.data(), quiet.size()) ==
           pipa::PipaVoiceActivityEvent::kSilence);
  }
  assert(!detector.speechActive());
  assert(detector.process(voice.data(), voice.size()) ==
         pipa::PipaVoiceActivityEvent::kSpeechStarted);
  assert(detector.speechActive());
  assert(detector.process(voice.data(), voice.size()) ==
         pipa::PipaVoiceActivityEvent::kSpeech);

  for (uint8_t index = 1; index < pipa::PipaVoiceActivityDetector::kEndSilenceChunks; ++index) {
    assert(detector.process(quiet.data(), quiet.size()) ==
           pipa::PipaVoiceActivityEvent::kSpeech);
  }
  assert(detector.process(quiet.data(), quiet.size()) ==
         pipa::PipaVoiceActivityEvent::kSpeechEnded);
  assert(!detector.speechActive());

  detector.resetUtterance();
  assert(detector.lastRms() == 0);
  assert(!detector.speechActive());
  assert(detector.process(nullptr, 0) == pipa::PipaVoiceActivityEvent::kSilence);

  // A high-gain microphone must learn a loud but steady room before it can
  // distinguish a nearby voice. This is the regression that previously kept
  // a hands-free capture open until its 30-second emergency limit.
  pipa::PipaVoiceActivityDetector high_gain_detector;
  const auto loud_room = alternating(2500);
  const auto nearby_voice = alternating(9000);
  for (uint8_t index = 0; index < pipa::PipaVoiceActivityDetector::kCalibrationChunks; ++index) {
    assert(high_gain_detector.process(loud_room.data(), loud_room.size()) ==
           pipa::PipaVoiceActivityEvent::kSilence);
  }
  assert(high_gain_detector.noiseFloorRms() >= 2400);
  assert(high_gain_detector.process(loud_room.data(), loud_room.size()) ==
         pipa::PipaVoiceActivityEvent::kSilence);
  assert(high_gain_detector.process(nearby_voice.data(), nearby_voice.size()) ==
         pipa::PipaVoiceActivityEvent::kSpeechStarted);
  for (uint8_t index = 1; index < pipa::PipaVoiceActivityDetector::kEndSilenceChunks; ++index) {
    assert(high_gain_detector.process(loud_room.data(), loud_room.size()) ==
           pipa::PipaVoiceActivityEvent::kSpeech);
  }
  assert(high_gain_detector.process(loud_room.data(), loud_room.size()) ==
         pipa::PipaVoiceActivityEvent::kSpeechEnded);
  return 0;
}
