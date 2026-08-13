#include "wake_on_lan_packet.h"

#include <cstring>

namespace {

int hexValue(char character) {
  if (character >= '0' && character <= '9') return character - '0';
  if (character >= 'a' && character <= 'f') return character - 'a' + 10;
  if (character >= 'A' && character <= 'F') return character - 'A' + 10;
  return -1;
}

bool parseMac(const char* text, std::uint8_t mac[6]) {
  if (text == nullptr || std::strlen(text) != 17) return false;
  const char separator = text[2];
  if (separator != ':' && separator != '-') return false;

  for (std::size_t index = 0; index < 6; ++index) {
    const std::size_t offset = index * 3;
    if (index != 5 && text[offset + 2] != separator) return false;
    const int high = hexValue(text[offset]);
    const int low = hexValue(text[offset + 1]);
    if (high < 0 || low < 0) return false;
    mac[index] = static_cast<std::uint8_t>((high << 4) | low);
  }

  bool all_zero = true;
  bool all_broadcast = true;
  for (std::size_t index = 0; index < 6; ++index) {
    all_zero = all_zero && mac[index] == 0;
    all_broadcast = all_broadcast && mac[index] == 0xFF;
  }

  // Wake-on-LAN targets a single NIC, never a multicast or unspecified MAC.
  return !all_zero && !all_broadcast && (mac[0] & 0x01u) == 0;
}

}  // namespace

namespace pipa {

bool buildWakeOnLanPacket(
    const char* mac_text,
    std::uint8_t* packet,
    std::size_t packet_capacity) {
  if (packet == nullptr || packet_capacity < kWakeOnLanPacketSize) return false;

  std::uint8_t mac[6] = {};
  if (!parseMac(mac_text, mac)) return false;

  std::memset(packet, 0, kWakeOnLanPacketSize);
  for (std::size_t index = 0; index < 6; ++index) packet[index] = 0xFF;
  for (std::size_t repeat = 0; repeat < 16; ++repeat) {
    std::memcpy(packet + 6 + repeat * 6, mac, 6);
  }
  return true;
}

}  // namespace pipa
