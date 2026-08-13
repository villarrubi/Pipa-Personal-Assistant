#pragma once

#include <Arduino.h>

#include <stddef.h>
#include <stdint.h>

#include "pipa_secure_session.h"

namespace pipa {

// Bounded v2 audio frame metadata plus the encrypted PCM record.  This type
// is a transport primitive only: it has no I2S, codec, microphone, speaker or
// serial ownership and is not a production firmware capability by itself.
struct PipaSecureAudioFrame {
  uint64_t sequence = 0;
  uint8_t audio_protocol_version = 2;
  uint8_t bits_per_sample = 16;
  uint8_t channels = 1;
  uint16_t chunk_index = 0;
  bool final = false;
  uint32_t sample_rate = 16000;
  char stream_id[65] = {};
  uint8_t ciphertext[4096 + PipaSecureSession::kTagBytes] = {};
  size_t ciphertext_length = 0;
};

class PipaSecureAudio {
 public:
  static constexpr uint8_t kProtocolVersion = 2;
  static constexpr uint32_t kSampleRate = 16000;
  static constexpr uint8_t kChannels = 1;
  static constexpr uint8_t kBitsPerSample = 16;
  static constexpr size_t kBytesPerSample = 2;
  static constexpr size_t kMaxChunkBytes = 4096;
  static constexpr size_t kMaxChunks = 64;
  static constexpr size_t kMaxStreamBytes = kMaxChunkBytes * kMaxChunks;
  static constexpr size_t kMaxStreamIdLength = 64;
  static constexpr size_t kMaxAdditionalDataBytes = 1024;

  static bool validStreamId(const char* stream_id);

  // Build exactly the AAD defined in SECURE_AUDIO_PROTOCOL.md.  The embedded
  // NUL after the prefix is intentional and is included in output_length.
  static bool buildAdditionalData(
      const char* stream_id,
      uint16_t chunk_index,
      bool final,
      uint8_t* output,
      size_t output_capacity,
      size_t* output_length);

  // Deterministic test vector only; no production route calls this method.
  static bool vectorSelfTest();
};

class PipaSecureAudioSender {
 public:
  PipaSecureAudioSender(PipaSecureSession& session, const char* stream_id);

  bool valid() const { return valid_; }
  bool complete() const { return finished_; }
  size_t streamBytes() const { return stream_bytes_; }

  bool sealChunk(
      const uint8_t* samples,
      size_t samples_length,
      bool final,
      PipaSecureAudioFrame& output);

  // A cancelled sender cannot be reused; a new sender starts a new stream
  // while preserving the enclosing secure session's record sequence.
  void cancel();

 private:
  PipaSecureSession& session_;
  char stream_id_[PipaSecureAudio::kMaxStreamIdLength + 1] = {};
  uint16_t next_chunk_ = 0;
  size_t stream_bytes_ = 0;
  bool valid_ = false;
  bool finished_ = false;
};

class PipaSecureAudioReceiver {
 public:
  explicit PipaSecureAudioReceiver(PipaSecureSession& session) : session_(session) {}

  bool complete() const { return finished_; }
  size_t streamBytes() const { return stream_bytes_; }

  bool openChunk(
      const PipaSecureAudioFrame& frame,
      uint8_t* output,
      size_t output_capacity,
      size_t* output_length);

  // Cancel clears only stream bookkeeping.  The secure control session stays
  // usable; close() additionally destroys that session.
  void cancel();
  void close();

 private:
  void failClosed(uint8_t* output, size_t output_capacity, size_t* output_length);

  PipaSecureSession& session_;
  char stream_id_[PipaSecureAudio::kMaxStreamIdLength + 1] = {};
  uint16_t next_chunk_ = 0;
  size_t stream_bytes_ = 0;
  bool has_stream_ = false;
  bool finished_ = false;
};

}  // namespace pipa
