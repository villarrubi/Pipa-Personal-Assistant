#include "pipa_audio_state.h"

namespace pipa {

const char* pipaAudioStateName(PipaAudioState state) {
  switch (state) {
    case PipaAudioState::kDisabled:
      return "disabled";
    case PipaAudioState::kProbeOnly:
      return "probe_only";
    case PipaAudioState::kCodecReady:
      return "codec_ready";
    case PipaAudioState::kListening:
      return "listening";
    case PipaAudioState::kDraining:
      return "draining";
    case PipaAudioState::kError:
      return "error";
  }
  return "error";
}

bool PipaAudioStateMachine::beginProbe() {
  if (state_ == PipaAudioState::kProbeOnly) return true;
  if (state_ != PipaAudioState::kDisabled && state_ != PipaAudioState::kError) {
    return false;
  }
  state_ = PipaAudioState::kProbeOnly;
  return true;
}

bool PipaAudioStateMachine::markCodecReady(bool codec_initialized) {
  if (state_ != PipaAudioState::kProbeOnly) return false;
  if (!codec_initialized) {
    state_ = PipaAudioState::kError;
    return false;
  }
  state_ = PipaAudioState::kCodecReady;
  return true;
}

bool PipaAudioStateMachine::beginListening(
    bool display_ready,
    bool consented,
    bool secure_transport_ready) {
  if (state_ != PipaAudioState::kCodecReady || !display_ready || !consented ||
      !secure_transport_ready) {
    return false;
  }
  state_ = PipaAudioState::kListening;
  return true;
}

bool PipaAudioStateMachine::beginDraining() {
  if (state_ != PipaAudioState::kListening) return false;
  state_ = PipaAudioState::kDraining;
  return true;
}

bool PipaAudioStateMachine::finishDraining() {
  if (state_ != PipaAudioState::kDraining) return false;
  state_ = PipaAudioState::kCodecReady;
  return true;
}

void PipaAudioStateMachine::fail() {
  state_ = PipaAudioState::kError;
}

bool PipaAudioStateMachine::canAdvertiseAudio() const {
  // Announce only from the stable ready state. Listening and draining are
  // deliberately not re-advertisable states, so a reconnect cannot mistake a
  // live or half-drained stream for a fresh capability declaration.
  return state_ == PipaAudioState::kCodecReady;
}

bool PipaAudioStateMachine::vectorSelfTest() {
  PipaAudioStateMachine gate;
  if (gate.state() != PipaAudioState::kDisabled || gate.canAdvertiseAudio() || gate.canCapture() ||
      gate.beginListening(true, true, true) || !gate.beginProbe() || !gate.beginProbe() ||
      gate.canAdvertiseAudio() || gate.markCodecReady(false) ||
      gate.state() != PipaAudioState::kError || gate.canAdvertiseAudio() ||
      gate.beginListening(true, true, true) || !gate.beginProbe() ||
      !gate.markCodecReady(true) || !gate.canAdvertiseAudio() || gate.canCapture()) {
    return false;
  }

  if (gate.beginListening(false, true, true) || gate.beginListening(true, false, true) ||
      gate.beginListening(true, true, false) ||
      !gate.beginListening(true, true, true) || !gate.canCapture() ||
      !gate.requiresVisibleIndicator() || gate.beginListening(true, true, true) ||
      !gate.beginDraining() || gate.canCapture() || gate.canAdvertiseAudio() ||
      gate.beginDraining() || !gate.finishDraining() || gate.canCapture()) {
    return false;
  }

  gate.fail();
  return gate.state() == PipaAudioState::kError && !gate.canAdvertiseAudio() &&
      !gate.canCapture() && gate.beginProbe() && gate.state() == PipaAudioState::kProbeOnly;
}

}  // namespace pipa
