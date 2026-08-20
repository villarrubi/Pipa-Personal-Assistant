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

  for (int index = 0; index < 12; ++index) {
    assert(detector.process(quiet.data(), quiet.size()) ==
           pipa::PipaVoiceActivityEvent::kSilence);
  }
  assert(!detector.speechActive());
  assert(detector.process(voice.data(), voice.size()) ==
         pipa::PipaVoiceActivityEvent::kSilence);
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
  return 0;
}
