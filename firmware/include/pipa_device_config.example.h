#pragma once

// When enabled, an authenticated PC may receive an encrypted utterance after
// local voice activity so its Spanish STT can verify the wake phrase. The
// offline phrase remains mandatory before Wake-on-LAN while the PC is off.
#ifndef PIPA_SERVER_WAKE_PHRASE_FALLBACK_ENABLED
#define PIPA_SERVER_WAKE_PHRASE_FALLBACK_ENABLED 0
#endif

// Copy this file to pipa_device_config.local.h. The copy is ignored by Git.
#define PIPA_WIFI_SSID ""
#define PIPA_WIFI_PASSWORD ""

// The PC's Ethernet/Wi-Fi MAC address, six hexadecimal bytes.
#define PIPA_PC_MAC "00:00:00:00:00:00"

// Keep disabled in ordinary voice-v2 builds. The dedicated hands-free
// environment enables persistent local VAD explicitly at compile time.
#ifndef PIPA_ALWAYS_LISTENING_ENABLED
#define PIPA_ALWAYS_LISTENING_ENABLED 0
#endif
#ifndef PIPA_LOCAL_WAKE_PHRASE_ENABLED
#define PIPA_LOCAL_WAKE_PHRASE_ENABLED 0
#endif

// USB CDC is the default authenticated transport after Windows starts.
#define PIPA_DEVICE_ID "waveshare-01"
#define PIPA_FIRMWARE_VERSION "0.1.0"

// Secure USB session v2 is opt-in. Provision the agent's public Ed25519 key
// out-of-band before enabling it on a physical device.
#ifndef PIPA_SECURE_SESSION_ENABLED
#define PIPA_SECURE_SESSION_ENABLED 0
#endif
#ifndef PIPA_AUDIO_CAPTURE_ENABLED
#define PIPA_AUDIO_CAPTURE_ENABLED 0
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
