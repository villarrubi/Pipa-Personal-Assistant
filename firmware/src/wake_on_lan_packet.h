#pragma once

#include <cstddef>
#include <cstdint>

namespace pipa {

constexpr std::size_t kWakeOnLanPacketSize = 102;

// Build a standard Wake-on-LAN magic packet without touching a network.
// The output buffer must have room for kWakeOnLanPacketSize bytes.
bool buildWakeOnLanPacket(
    const char* mac_text,
    std::uint8_t* packet,
    std::size_t packet_capacity);

}  // namespace pipa
