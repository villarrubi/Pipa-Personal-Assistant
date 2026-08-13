#include "../src/pipa_audio_state.h"

int main() {
  return pipa::PipaAudioStateMachine::vectorSelfTest() ? 0 : 1;
}
