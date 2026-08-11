#include "wake_on_lan.h"

namespace {

int hexValue(char character) {
  if (character >= '0' && character <= '9') return character - '0';
  if (character >= 'a' && character <= 'f') return character - 'a' + 10;
  if (character >= 'A' && character <= 'F') return character - 'A' + 10;
  return -1;
}

bool parseMac(const char* text, uint8_t mac[6]) {
  if (text == nullptr || strlen(text) != 17) return false;
  const char separator = text[2];
  if (separator != ':' && separator != '-') return false;
  for (size_t index = 0; index < 6; ++index) {
    const size_t offset = index * 3;
    if (index != 5 && text[offset + 2] != separator) return false;
    const int high = hexValue(text[offset]);
    const int low = hexValue(text[offset + 1]);
    if (high < 0 || low < 0) return false;
    mac[index] = static_cast<uint8_t>((high << 4) | low);
  }
  bool all_zero = true;
  bool all_broadcast = true;
  for (size_t index = 0; index < 6; ++index) {
    const uint8_t byte = mac[index];
    all_zero = all_zero && byte == 0;
    all_broadcast = all_broadcast && byte == 0xFF;
  }
  if (all_zero || all_broadcast) return false;
  return true;
}

}  // namespace

namespace pipa {

bool WakeOnLan::send(const char* mac_text) {
  uint8_t mac[6] = {};
  if (!parseMac(mac_text, mac)) return false;

  uint8_t packet[102] = {};
  for (size_t index = 0; index < 6; ++index) packet[index] = 0xFF;
  for (size_t repeat = 0; repeat < 16; ++repeat) {
    memcpy(packet + 6 + repeat * 6, mac, 6);
  }

  if (!udp_.beginPacket(IPAddress(255, 255, 255, 255), 9)) return false;
  udp_.write(packet, sizeof(packet));
  return udp_.endPacket() == 1;
}

}  // namespace pipa
