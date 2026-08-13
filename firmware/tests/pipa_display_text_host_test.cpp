#include <cassert>
#include <string>

#include "pipa_display_text.h"

int main() {
  using pipa::display_text::normalizeSummary;
  using pipa::display_text::splitSummary;

  assert(normalizeSummary("  Preparar acción: mamá\r\n") == "PREPARAR ACCION: MAMA");
  assert(normalizeSummary("Pip\xCE\xB1") == "PIP?");
  const char truncated_utf8[] = "Pip\xC3";
  assert(normalizeSummary(truncated_utf8) == "PIP?");
  assert(normalizeSummary("\n\r  ").empty());
  assert(normalizeSummary(nullptr).empty());

  const std::string long_word(120, 'x');
  const std::string normalized = normalizeSummary(long_word.c_str());
  assert(normalized.size() == pipa::display_text::kMaxSummaryBytes);

  std::string first;
  std::string second;
  splitSummary("Buscar en Apple Music: Daft Punk", first, second);
  assert(first == "Buscar en Apple Music:");
  assert(second == "Daft Punk");
  splitSummary(long_word.c_str(), first, second);
  assert(first.size() == pipa::display_text::kMaxLineCharacters);
  assert(second.size() == pipa::display_text::kMaxLineCharacters);
  splitSummary(nullptr, first, second);
  assert(first.empty() && second.empty());

  return 0;
}
