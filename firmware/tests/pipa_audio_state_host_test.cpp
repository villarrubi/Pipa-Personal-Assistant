#include "../src/pipa_audio_state.h"

#include <cstring>

int main() {
  if (!pipa::PipaAudioStateMachine::vectorSelfTest()) return 1;
  if (strcmp(pipa::pipaAudioStateName(pipa::PipaAudioState::kDisabled), "disabled") != 0 ||
      strcmp(pipa::pipaAudioStateName(pipa::PipaAudioState::kProbeOnly), "probe_only") != 0 ||
      strcmp(pipa::pipaAudioStateName(pipa::PipaAudioState::kCodecReady), "codec_ready") != 0 ||
      strcmp(pipa::pipaAudioStateName(pipa::PipaAudioState::kListening), "listening") != 0 ||
      strcmp(pipa::pipaAudioStateName(pipa::PipaAudioState::kDraining), "draining") != 0 ||
      strcmp(pipa::pipaAudioStateName(pipa::PipaAudioState::kError), "error") != 0) {
    return 1;
  }
  return 0;
}
