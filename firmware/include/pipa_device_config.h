#pragma once

// Safe build defaults. Real credentials must be supplied through a local
// pipa_device_config.h replacement or PlatformIO build flags.
#define PIPA_WIFI_SSID ""
#define PIPA_WIFI_PASSWORD ""
#define PIPA_PC_MAC "00:00:00:00:00:00"

#ifndef PIPA_ALWAYS_LISTENING_ENABLED
#define PIPA_ALWAYS_LISTENING_ENABLED 0
#endif
#ifndef PIPA_LOCAL_WAKE_PHRASE_ENABLED
#define PIPA_LOCAL_WAKE_PHRASE_ENABLED 0
#endif
#ifndef PIPA_SERVER_WAKE_PHRASE_FALLBACK_ENABLED
#define PIPA_SERVER_WAKE_PHRASE_FALLBACK_ENABLED 0
#endif
#define PIPA_DEVICE_ID "waveshare-01"
#define PIPA_FIRMWARE_VERSION "0.1.0"
#ifndef PIPA_SECURE_SESSION_ENABLED
#define PIPA_SECURE_SESSION_ENABLED 0
#endif
#ifndef PIPA_AUDIO_CAPTURE_ENABLED
#define PIPA_AUDIO_CAPTURE_ENABLED 0
#endif
#define PIPA_SECURE_SERVER_ID "pipa-agent-v2"
#define PIPA_SECURE_SERVER_PUBLIC_KEY ""
// Waveshare V2 is the current hardware; set to 1 only for a confirmed V1 PCB.
// PlatformIO's V1 compatibility environment overrides this at compile time.
#ifndef PIPA_BOARD_REVISION
#define PIPA_BOARD_REVISION 2
#endif
