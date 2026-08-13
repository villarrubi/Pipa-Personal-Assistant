#include "pipa_secure_audio.h"

#include <string.h>

namespace pipa {
namespace {

constexpr char kAudioPrefix[] = "pipa/audio/v2";

bool validSamples(const uint8_t* samples, size_t length) {
  return samples != nullptr && length > 0 && length <= PipaSecureAudio::kMaxChunkBytes &&
      length % PipaSecureAudio::kBytesPerSample == 0;
}

bool copyStreamId(const char* source, char* destination, size_t destination_capacity) {
  if (!PipaSecureAudio::validStreamId(source) || destination == nullptr ||
      destination_capacity < PipaSecureAudio::kMaxStreamIdLength + 1) {
    return false;
  }
  const size_t length = strlen(source);
  memset(destination, 0, destination_capacity);
  memcpy(destination, source, length);
  return true;
}

}  // namespace

bool PipaSecureAudio::validStreamId(const char* stream_id) {
  if (stream_id == nullptr || stream_id[0] == '\0') return false;
  size_t length = 0;
  while (stream_id[length] != '\0') {
    if (++length > kMaxStreamIdLength) return false;
    const char character = stream_id[length - 1];
    if (!((character >= 'a' && character <= 'z') ||
          (character >= 'A' && character <= 'Z') ||
          (character >= '0' && character <= '9') || character == '-' || character == '_')) {
      return false;
    }
  }
  return true;
}

bool PipaSecureAudio::buildAdditionalData(
    const char* stream_id,
    uint16_t chunk_index,
    bool final,
    uint8_t* output,
    size_t output_capacity,
    size_t* output_length) {
  if (output_length != nullptr) *output_length = 0;
  if (!validStreamId(stream_id) || chunk_index >= kMaxChunks || output == nullptr ||
      output_length == nullptr) {
    return false;
  }
  if (chunk_index == kMaxChunks - 1 && !final) return false;

  String json;
  json.reserve(160);
  json += "{\"audio_protocol_version\":2,\"bits_per_sample\":16,";
  json += "\"channels\":1,\"chunk_index\":";
  json += String(static_cast<unsigned int>(chunk_index));
  json += ",\"final\":";
  json += final ? "true" : "false";
  json += ",\"sample_rate\":16000,\"stream_id\":\"";
  json += stream_id;
  json += "\"}";

  const size_t prefix_length = sizeof(kAudioPrefix) - 1;
  const size_t required = prefix_length + 1 + json.length();
  if (required > output_capacity || required > kMaxAdditionalDataBytes) return false;
  memcpy(output, kAudioPrefix, prefix_length);
  output[prefix_length] = 0;
  memcpy(output + prefix_length + 1, json.c_str(), json.length());
  *output_length = required;
  return true;
}

PipaSecureAudioSender::PipaSecureAudioSender(
    PipaSecureSession& session,
    const char* stream_id)
    : session_(session) {
  valid_ = copyStreamId(stream_id, stream_id_, sizeof(stream_id_));
}

bool PipaSecureAudioSender::sealChunk(
    const uint8_t* samples,
    size_t samples_length,
    bool final,
    PipaSecureAudioFrame& output) {
  if (!valid_ || finished_ || !session_.ready() || !validSamples(samples, samples_length) ||
      next_chunk_ >= PipaSecureAudio::kMaxChunks ||
      stream_bytes_ + samples_length > PipaSecureAudio::kMaxStreamBytes ||
      (next_chunk_ == PipaSecureAudio::kMaxChunks - 1 && !final)) {
    return false;
  }

  uint8_t additional_data[PipaSecureAudio::kMaxAdditionalDataBytes] = {};
  size_t additional_data_length = 0;
  if (!PipaSecureAudio::buildAdditionalData(
          stream_id_,
          next_chunk_,
          final,
          additional_data,
          sizeof(additional_data),
          &additional_data_length)) {
    return false;
  }

  memset(&output, 0, sizeof(output));
  output.sequence = session_.nextSendSequence();
  output.audio_protocol_version = PipaSecureAudio::kProtocolVersion;
  output.bits_per_sample = PipaSecureAudio::kBitsPerSample;
  output.channels = PipaSecureAudio::kChannels;
  output.chunk_index = next_chunk_;
  output.final = final;
  output.sample_rate = PipaSecureAudio::kSampleRate;
  memcpy(output.stream_id, stream_id_, sizeof(output.stream_id));
  if (!session_.seal(
          samples,
          samples_length,
          additional_data,
          additional_data_length,
          output.ciphertext,
          sizeof(output.ciphertext),
          &output.ciphertext_length)) {
    memset(&output, 0, sizeof(output));
    return false;
  }

  ++next_chunk_;
  stream_bytes_ += samples_length;
  finished_ = final;
  return true;
}

void PipaSecureAudioSender::cancel() {
  finished_ = true;
  next_chunk_ = 0;
  stream_bytes_ = 0;
}

bool PipaSecureAudioReceiver::openChunk(
    const PipaSecureAudioFrame& frame,
    uint8_t* output,
    size_t output_capacity,
    size_t* output_length) {
  if (output_length != nullptr) *output_length = 0;
  if (output == nullptr || output_length == nullptr || !session_.ready() || finished_ ||
      frame.audio_protocol_version != PipaSecureAudio::kProtocolVersion ||
      frame.bits_per_sample != PipaSecureAudio::kBitsPerSample ||
      frame.channels != PipaSecureAudio::kChannels ||
      frame.sample_rate != PipaSecureAudio::kSampleRate ||
      frame.chunk_index >= PipaSecureAudio::kMaxChunks ||
      frame.sequence != session_.nextReceiveSequence() ||
      frame.ciphertext_length < PipaSecureSession::kTagBytes ||
      frame.ciphertext_length > PipaSecureAudio::kMaxChunkBytes + PipaSecureSession::kTagBytes ||
      !PipaSecureAudio::validStreamId(frame.stream_id) ||
      (!has_stream_ && frame.chunk_index != 0) ||
      (has_stream_ && strcmp(frame.stream_id, stream_id_) != 0) ||
      frame.chunk_index != next_chunk_) {
    failClosed(output, output_capacity, output_length);
    return false;
  }

  const size_t expected_plaintext_length =
      frame.ciphertext_length - PipaSecureSession::kTagBytes;
  if (expected_plaintext_length > output_capacity) {
    failClosed(output, output_capacity, output_length);
    return false;
  }

  uint8_t additional_data[PipaSecureAudio::kMaxAdditionalDataBytes] = {};
  size_t additional_data_length = 0;
  if (!PipaSecureAudio::buildAdditionalData(
          frame.stream_id,
          frame.chunk_index,
          frame.final,
          additional_data,
          sizeof(additional_data),
          &additional_data_length) ||
      !session_.open(
          frame.sequence,
          frame.ciphertext,
          frame.ciphertext_length,
          additional_data,
          additional_data_length,
          output,
          output_capacity,
          output_length)) {
    failClosed(output, output_capacity, output_length);
    return false;
  }

  if (*output_length == 0 || *output_length > PipaSecureAudio::kMaxChunkBytes ||
      *output_length % PipaSecureAudio::kBytesPerSample != 0 ||
      stream_bytes_ + *output_length > PipaSecureAudio::kMaxStreamBytes) {
    failClosed(output, output_capacity, output_length);
    return false;
  }

  if (!has_stream_ && !copyStreamId(frame.stream_id, stream_id_, sizeof(stream_id_))) {
    failClosed(output, output_capacity, output_length);
    return false;
  }
  has_stream_ = true;
  ++next_chunk_;
  stream_bytes_ += *output_length;
  finished_ = frame.final;
  return true;
}

void PipaSecureAudioReceiver::cancel() {
  memset(stream_id_, 0, sizeof(stream_id_));
  next_chunk_ = 0;
  stream_bytes_ = 0;
  has_stream_ = false;
  finished_ = false;
}

void PipaSecureAudioReceiver::close() {
  cancel();
  session_.clear();
}

void PipaSecureAudioReceiver::failClosed(
    uint8_t* output,
    size_t output_capacity,
    size_t* output_length) {
  if (output_length != nullptr) *output_length = 0;
  if (output != nullptr && output_capacity > 0) memset(output, 0, output_capacity);
  cancel();
  session_.clear();
}

bool PipaSecureAudio::vectorSelfTest() {
  static constexpr uint8_t shared_secret[PipaSecureSession::kKeyBytes] = {
      0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
      0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x10,
      0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18,
      0x19, 0x1A, 0x1B, 0x1C, 0x1D, 0x1E, 0x1F, 0x20};
  static constexpr uint8_t transcript_hash[PipaSecureSession::kTranscriptHashBytes] = {
      0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27,
      0x28, 0x29, 0x2A, 0x2B, 0x2C, 0x2D, 0x2E, 0x2F,
      0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0x36, 0x37,
      0x38, 0x39, 0x3A, 0x3B, 0x3C, 0x3D, 0x3E, 0x3F};
  static constexpr uint8_t samples[] = {
      0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07,
      0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F,
      0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17,
      0x18, 0x19, 0x1A, 0x1B, 0x1C, 0x1D, 0x1E, 0x1F};
  static constexpr uint8_t expected_ciphertext_and_tag[] = {
      0xD6, 0x53, 0xE5, 0x78, 0xE2, 0xB6, 0x3A, 0x43,
      0xE7, 0xFF, 0xBA, 0xA3, 0x97, 0x33, 0x82, 0xB7,
      0x3E, 0x29, 0x4F, 0x00, 0x80, 0x25, 0x9B, 0x53,
      0xB3, 0x53, 0x62, 0x94, 0xFC, 0x91, 0x10, 0xF1,
      0xC2, 0xFF, 0x6E, 0x11, 0xC2, 0x3F, 0x20, 0x60,
      0x56, 0x5D, 0x04, 0x6E, 0x16, 0x6B, 0x67, 0xDA};

  PipaSecureSession client;
  PipaSecureSession server;
  if (!client.beginFromSharedSecret("audio-vector", shared_secret, transcript_hash, true) ||
      !server.beginFromSharedSecret("audio-vector", shared_secret, transcript_hash, false)) {
    return false;
  }
  PipaSecureAudioSender sender(client, "audio-test");
  static PipaSecureAudioFrame frame = {};
  if (!sender.valid() || !sender.sealChunk(samples, sizeof(samples), true, frame) ||
      frame.ciphertext_length != sizeof(expected_ciphertext_and_tag) ||
      memcmp(frame.ciphertext, expected_ciphertext_and_tag, sizeof(expected_ciphertext_and_tag)) != 0) {
    return false;
  }

  PipaSecureAudioReceiver receiver(server);
  static uint8_t opened[sizeof(samples)] = {};
  size_t opened_length = 0;
  if (!receiver.openChunk(frame, opened, sizeof(opened), &opened_length) ||
      !receiver.complete() || opened_length != sizeof(samples) ||
      memcmp(opened, samples, sizeof(samples)) != 0) {
    return false;
  }

  PipaSecureSession tampered_server;
  if (!tampered_server.beginFromSharedSecret(
          "audio-vector", shared_secret, transcript_hash, false)) {
    return false;
  }
  PipaSecureAudioFrame tampered = frame;
  tampered.final = false;
  PipaSecureAudioReceiver tampered_receiver(tampered_server);
  return !tampered_receiver.openChunk(tampered, opened, sizeof(opened), &opened_length) &&
      !tampered_server.ready();
}

}  // namespace pipa
