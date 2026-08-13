#pragma once

#include <stdint.h>

namespace pipa {

// This policy state is deliberately independent from Arduino, I2C and I2S.
// It is the gate a future physical audio driver must pass before it can ever
// expose a capture route to the rest of the firmware.
enum class PipaAudioState : uint8_t {
  kDisabled = 0,
  kProbeOnly = 1,
  kCodecReady = 2,
  kListening = 3,
  kDraining = 4,
  kError = 5,
};

// Stable wire labels for diagnostics. These labels describe the gate state,
// not permission to capture: only LISTENING means that a future driver may
// have an active capture route.
const char* pipaAudioStateName(PipaAudioState state);

class PipaAudioStateMachine {
 public:
  PipaAudioState state() const { return state_; }

  // Only a known-safe initialization path may enter the probe state. Repeating
  // a passive probe is idempotent; a failed active session must go through
  // this boundary before it can be retried.
  bool beginProbe();

  // The physical driver calls this only after codec, clocks and I2S pass its
  // own bounded initialization. A failed initialization is terminal until a
  // fresh probe is requested.
  bool markCodecReady(bool codec_initialized);

  // Listening requires all three independent gates: visible UI, explicit
  // consent and an authenticated/encrypted transport.
  bool beginListening(bool display_ready, bool consented, bool secure_transport_ready);
  bool beginDraining();
  bool finishDraining();

  // Any unexpected hardware, buffer or transport failure closes the gate.
  void fail();

  // True only in the stable CODEC_READY state; LISTENING/DRAINING must not
  // be mistaken for a fresh capability announcement after reconnect.
  bool canAdvertiseAudio() const;
  bool canCapture() const { return state_ == PipaAudioState::kListening; }
  bool requiresVisibleIndicator() const { return canCapture(); }

  // Deterministic transition test used only by the secure-session-vector
  // environment. It has no hardware side effects.
  static bool vectorSelfTest();

 private:
  PipaAudioState state_ = PipaAudioState::kDisabled;
};

}  // namespace pipa
