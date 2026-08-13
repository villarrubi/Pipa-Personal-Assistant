#pragma once

// Copy this file to pipa_device_config.local.h. The copy is ignored by Git.
#define PIPA_WIFI_SSID "replace-me"
#define PIPA_WIFI_PASSWORD "replace-me"

// The PC's Ethernet/Wi-Fi MAC address, six hexadecimal bytes.
#define PIPA_PC_MAC "AA:BB:CC:DD:EE:FF"

// USB CDC is the default authenticated transport after Windows starts.
#define PIPA_DEVICE_ID "waveshare-01"
#define PIPA_FIRMWARE_VERSION "0.1.0"

// Secure USB session v2 is opt-in. Provision the agent's public Ed25519 key
// out-of-band before enabling it on a physical device.
#ifndef PIPA_SECURE_SESSION_ENABLED
#define PIPA_SECURE_SESSION_ENABLED 0
#endif
#define PIPA_SECURE_SERVER_ID "pipa-agent-v2"
#define PIPA_SECURE_SERVER_PUBLIC_KEY ""

// Board revision: 1 for the older V1 wiring, 2 for the current V2 wiring.
// V2 uses I2C GPIO10/11 and ES8311/ES7210 audio.
#ifndef PIPA_BOARD_REVISION
#define PIPA_BOARD_REVISION 2
#endif

// The device is intentionally not configured with a remote/cloud endpoint.
// Remote access must be provided by a separately reviewed relay.
