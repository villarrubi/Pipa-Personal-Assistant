#include "device_identity.h"

#include <Ed25519.h>
#include <esp_system.h>
#include <string.h>

namespace pipa {

bool DeviceIdentity::begin() {
  ready_ = false;
  memset(private_key_, 0, sizeof(private_key_));
  memset(public_key_, 0, sizeof(public_key_));
  if (!preferences_.begin("pipa", false)) return false;

  const size_t stored_length = preferences_.getBytesLength("private");
  if (stored_length == sizeof(private_key_)) {
    if (preferences_.getBytes("private", private_key_, sizeof(private_key_)) != sizeof(private_key_)) {
      preferences_.end();
      memset(private_key_, 0, sizeof(private_key_));
      return false;
    }
  } else if (stored_length == 0) {
    esp_fill_random(private_key_, sizeof(private_key_));
    if (preferences_.putBytes("private", private_key_, sizeof(private_key_)) != sizeof(private_key_)) {
      preferences_.end();
      memset(private_key_, 0, sizeof(private_key_));
      return false;
    }
  } else {
    // Never replace a malformed identity silently: doing so would break the
    // administrator-approved device/key binding.
    preferences_.end();
    memset(private_key_, 0, sizeof(private_key_));
    return false;
  }

  preferences_.end();
  Ed25519::derivePublicKey(public_key_, private_key_);
  ready_ = true;
  return true;
}

String DeviceIdentity::publicKeyBase64Url() const {
  return ready_ ? encodeBase64Url(public_key_, sizeof(public_key_)) : String();
}

String DeviceIdentity::signBase64Url(const String& message) const {
  if (!ready_) return String();
  uint8_t signature[64] = {};
  Ed25519::sign(
      signature,
      private_key_,
      public_key_,
      message.c_str(),
      message.length());
  return encodeBase64Url(signature, sizeof(signature));
}

String DeviceIdentity::encodeBase64Url(const uint8_t* bytes, size_t length) {
  static constexpr char alphabet[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
  String value;
  value.reserve(((length + 2) / 3) * 4);
  for (size_t index = 0; index < length; index += 3) {
    const uint32_t block = static_cast<uint32_t>(bytes[index]) << 16 |
                           static_cast<uint32_t>(index + 1 < length ? bytes[index + 1] : 0) << 8 |
                           static_cast<uint32_t>(index + 2 < length ? bytes[index + 2] : 0);
    value += alphabet[(block >> 18) & 0x3F];
    value += alphabet[(block >> 12) & 0x3F];
    if (index + 1 < length) value += alphabet[(block >> 6) & 0x3F];
    if (index + 2 < length) value += alphabet[block & 0x3F];
  }
  return value;
}

}  // namespace pipa
