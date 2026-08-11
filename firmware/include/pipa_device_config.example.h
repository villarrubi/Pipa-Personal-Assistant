#pragma once

// Copy this file to pipa_device_config.h. The copy is ignored by Git.
#define PIPA_WIFI_SSID "replace-me"
#define PIPA_WIFI_PASSWORD "replace-me"

// The PC's Ethernet/Wi-Fi MAC address, six hexadecimal bytes.
#define PIPA_PC_MAC "AA:BB:CC:DD:EE:FF"

// USB CDC is the default authenticated transport after Windows starts.
#define PIPA_DEVICE_ID "waveshare-01"
#define PIPA_FIRMWARE_VERSION "0.1.0"

// Board revision: 1 for the older V1 audio wiring, 2 for the current V2.
#define PIPA_BOARD_REVISION 2

// The device is intentionally not configured with a remote/cloud endpoint.
// Remote access must be provided by a separately reviewed relay.
