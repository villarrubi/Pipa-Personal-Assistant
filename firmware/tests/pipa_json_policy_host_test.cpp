#include <cassert>
#include <string>

#include "pipa_json_policy.h"

int main() {
  using pipa::isDuplicateFreeJson;
  const auto accepts = [](const char* json) {
    return isDuplicateFreeJson(json, std::char_traits<char>::length(json));
  };
  const auto rejects = [](const char* json) {
    return !isDuplicateFreeJson(json, std::char_traits<char>::length(json));
  };

  assert(accepts("{}"));
  assert(accepts("{\"type\":\"ping\",\"request_id\":\"one\"}"));
  assert(accepts("{\"nested\":{\"value\":1},\"items\":[{\"value\":2}]}"));
  assert(accepts("{\"a\\u0062\":1,\"emoji\":\"\\uD83D\\uDE00\"}"));

  assert(rejects("{\"type\":\"ping\",\"type\":\"confirm\"}"));
  assert(rejects("{\"outer\":{\"a\":1,\"a\":2}}"));
  assert(rejects("{\"ab\":1,\"a\\u0062\":2}"));
  assert(rejects("{\"items\":[{\"a\":1,\"a\":2}]}"));
  assert(rejects("{\"broken\":\"\\uD83D\"}"));
  assert(rejects("{\"type\":1"));
  assert(!isDuplicateFreeJson(nullptr, 0));
  assert(!isDuplicateFreeJson("{}", 1));
  return 0;
}
