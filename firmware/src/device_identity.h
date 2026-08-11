#pragma once

#include <Arduino.h>
#include <Preferences.h>

namespace pipa {

class DeviceIdentity {
 public:
  bool begin();
  bool ready() const { return ready_; }
  String publicKeyBase64Url() const;
  String signBase64Url(const String& message) const;

 private:
  static String encodeBase64Url(const uint8_t* bytes, size_t length);

  Preferences preferences_;
  uint8_t private_key_[32] = {};
  uint8_t public_key_[32] = {};
  bool ready_ = false;
};

}  // namespace pipa
