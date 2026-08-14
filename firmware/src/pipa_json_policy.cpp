#include "pipa_json_policy.h"

#include <cstdint>
#include <string>
#include <utility>
#include <vector>

namespace pipa {
namespace {

constexpr std::size_t kMaxNesting = 32;

bool isWhitespace(char character) {
  return character == ' ' || character == '\t' || character == '\n' || character == '\r';
}

int hexValue(char character) {
  if (character >= '0' && character <= '9') return character - '0';
  if (character >= 'a' && character <= 'f') return character - 'a' + 10;
  if (character >= 'A' && character <= 'F') return character - 'A' + 10;
  return -1;
}

void appendCodepoint(std::string& output, std::uint32_t codepoint) {
  if (codepoint <= 0x7F) {
    output.push_back(static_cast<char>(codepoint));
  } else if (codepoint <= 0x7FF) {
    output.push_back(static_cast<char>(0xC0 | (codepoint >> 6)));
    output.push_back(static_cast<char>(0x80 | (codepoint & 0x3F)));
  } else if (codepoint <= 0xFFFF) {
    output.push_back(static_cast<char>(0xE0 | (codepoint >> 12)));
    output.push_back(static_cast<char>(0x80 | ((codepoint >> 6) & 0x3F)));
    output.push_back(static_cast<char>(0x80 | (codepoint & 0x3F)));
  } else {
    output.push_back(static_cast<char>(0xF0 | (codepoint >> 18)));
    output.push_back(static_cast<char>(0x80 | ((codepoint >> 12) & 0x3F)));
    output.push_back(static_cast<char>(0x80 | ((codepoint >> 6) & 0x3F)));
    output.push_back(static_cast<char>(0x80 | (codepoint & 0x3F)));
  }
}

class JsonScanner {
 public:
  JsonScanner(const char* json, std::size_t length) : json_(json), length_(length) {}

  bool duplicateFree() {
    if (json_ == nullptr || length_ == 0) return false;
    skipWhitespace();
    if (!parseValue(0)) return false;
    skipWhitespace();
    return position_ == length_;
  }

 private:
  void skipWhitespace() {
    while (position_ < length_ && isWhitespace(json_[position_])) ++position_;
  }

  bool consume(char expected) {
    if (position_ >= length_ || json_[position_] != expected) return false;
    ++position_;
    return true;
  }

  bool parseValue(std::size_t depth) {
    if (depth > kMaxNesting) return false;
    skipWhitespace();
    if (position_ >= length_) return false;
    switch (json_[position_]) {
      case '{':
        return parseObject(depth + 1);
      case '[':
        return parseArray(depth + 1);
      case '"': {
        std::string ignored;
        return parseString(&ignored);
      }
      case 't':
        return consumeLiteral("true");
      case 'f':
        return consumeLiteral("false");
      case 'n':
        return consumeLiteral("null");
      default:
        return parseNumber();
    }
  }

  bool parseObject(std::size_t depth) {
    if (!consume('{')) return false;
    skipWhitespace();
    if (consume('}')) return true;

    std::vector<std::string> keys;
    while (true) {
      std::string key;
      if (!parseString(&key)) return false;
      for (const std::string& previous : keys) {
        if (previous == key) return false;
      }
      keys.push_back(std::move(key));
      skipWhitespace();
      if (!consume(':') || !parseValue(depth)) return false;
      skipWhitespace();
      if (consume('}')) return true;
      if (!consume(',')) return false;
      skipWhitespace();
    }
  }

  bool parseArray(std::size_t depth) {
    if (!consume('[')) return false;
    skipWhitespace();
    if (consume(']')) return true;
    while (true) {
      if (!parseValue(depth)) return false;
      skipWhitespace();
      if (consume(']')) return true;
      if (!consume(',')) return false;
      skipWhitespace();
    }
  }

  bool parseString(std::string* output) {
    if (!consume('"')) return false;
    if (output != nullptr) output->clear();
    while (position_ < length_) {
      const unsigned char character = static_cast<unsigned char>(json_[position_++]);
      if (character == '"') return true;
      if (character < 0x20) return false;
      if (character != '\\') {
        if (output != nullptr) output->push_back(static_cast<char>(character));
        continue;
      }
      if (position_ >= length_) return false;
      const char escape = json_[position_++];
      switch (escape) {
        case '"':
        case '\\':
        case '/':
          if (output != nullptr) output->push_back(escape);
          break;
        case 'b':
          if (output != nullptr) output->push_back('\b');
          break;
        case 'f':
          if (output != nullptr) output->push_back('\f');
          break;
        case 'n':
          if (output != nullptr) output->push_back('\n');
          break;
        case 'r':
          if (output != nullptr) output->push_back('\r');
          break;
        case 't':
          if (output != nullptr) output->push_back('\t');
          break;
        case 'u': {
          std::uint16_t code_unit = 0;
          if (!readUnicodeEscape(code_unit)) return false;
          if (code_unit >= 0xD800 && code_unit <= 0xDBFF) {
            if (position_ + 1 >= length_ || json_[position_] != '\\' || json_[position_ + 1] != 'u') {
              return false;
            }
            position_ += 2;
            std::uint16_t low = 0;
            if (!readUnicodeEscape(low) || low < 0xDC00 || low > 0xDFFF) return false;
            const std::uint32_t codepoint =
                0x10000 + ((static_cast<std::uint32_t>(code_unit) - 0xD800) << 10) +
                (static_cast<std::uint32_t>(low) - 0xDC00);
            if (output != nullptr) appendCodepoint(*output, codepoint);
          } else {
            if (code_unit >= 0xDC00 && code_unit <= 0xDFFF) return false;
            if (output != nullptr) appendCodepoint(*output, code_unit);
          }
          break;
        }
        default:
          return false;
      }
    }
    return false;
  }

  bool readUnicodeEscape(std::uint16_t& code_unit) {
    if (position_ + 4 > length_) return false;
    code_unit = 0;
    for (std::size_t index = 0; index < 4; ++index) {
      const int digit = hexValue(json_[position_++]);
      if (digit < 0) return false;
      code_unit = static_cast<std::uint16_t>((code_unit << 4) | digit);
    }
    return true;
  }

  bool consumeLiteral(const char* literal) {
    for (const char* cursor = literal; *cursor != '\0'; ++cursor) {
      if (position_ >= length_ || json_[position_++] != *cursor) return false;
    }
    return true;
  }

  bool parseNumber() {
    const std::size_t start = position_;
    if (position_ < length_ && json_[position_] == '-') ++position_;
    while (position_ < length_ && json_[position_] >= '0' && json_[position_] <= '9') ++position_;
    if (position_ < length_ && json_[position_] == '.') {
      ++position_;
      while (position_ < length_ && json_[position_] >= '0' && json_[position_] <= '9') ++position_;
    }
    if (position_ < length_ && (json_[position_] == 'e' || json_[position_] == 'E')) {
      ++position_;
      if (position_ < length_ && (json_[position_] == '+' || json_[position_] == '-')) ++position_;
      while (position_ < length_ && json_[position_] >= '0' && json_[position_] <= '9') ++position_;
    }
    return position_ > start;
  }

  const char* json_;
  std::size_t length_;
  std::size_t position_ = 0;
};

}  // namespace

bool isDuplicateFreeJson(const char* json, std::size_t length) {
  return JsonScanner(json, length).duplicateFree();
}

}  // namespace pipa
