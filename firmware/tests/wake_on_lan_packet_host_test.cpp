#include <cassert>
#include <cstdint>
#include <cstring>

#include "wake_on_lan_packet.h"

namespace {

void assertPacket(const std::uint8_t* packet, const std::uint8_t mac[6]) {
  for (std::size_t index = 0; index < 6; ++index) assert(packet[index] == 0xFF);
  for (std::size_t repeat = 0; repeat < 16; ++repeat) {
    assert(std::memcmp(packet + 6 + repeat * 6, mac, 6) == 0);
  }
}

}  // namespace

int main() {
  constexpr std::uint8_t mac[6] = {0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xF0};
  std::uint8_t packet[pipa::kWakeOnLanPacketSize + 1] = {};
  packet[pipa::kWakeOnLanPacketSize] = 0x5A;

  assert(pipa::buildWakeOnLanPacket("AA:BB:CC:DD:EE:F0", packet, sizeof(packet)));
  assertPacket(packet, mac);
  assert(packet[pipa::kWakeOnLanPacketSize] == 0x5A);

  assert(pipa::buildWakeOnLanPacket("aa-bb-cc-dd-ee-f0", packet, sizeof(packet)));
  assertPacket(packet, mac);

  const char* invalid[] = {
      nullptr,
      "00:00:00:00:00:00",
      "FF:FF:FF:FF:FF:FF",
      "01:BB:CC:DD:EE:F0",
      "AA:BB:CC:DD:EE",
      "AA:BB-CC:DD:EE:F0",
      "AA:BB:CC:DD:EE:GG",
  };
  for (const char* value : invalid) {
    assert(!pipa::buildWakeOnLanPacket(value, packet, sizeof(packet)));
  }

  std::memset(packet, 0xA5, sizeof(packet));
  assert(!pipa::buildWakeOnLanPacket("AA:BB:CC:DD:EE:F0", packet, 101));
  for (const std::uint8_t byte : packet) assert(byte == 0xA5);
  assert(!pipa::buildWakeOnLanPacket("AA:BB:CC:DD:EE:F0", nullptr, 102));
  return 0;
}
