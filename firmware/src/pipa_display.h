#pragma once

#include <Arduino.h>
#include <esp_lcd_types.h>

#include "pipa_protocol.h"
#include "tca9554.h"

namespace pipa {

class PipaDisplay {
 public:
  static constexpr uint16_t kWidth = 360;
  static constexpr uint16_t kHeight = 360;

  bool begin(Tca9554* io_expander);
  void render(const UiSnapshot& snapshot);
  bool ready() const { return ready_; }

 private:
  void drawRow(
      uint16_t* row_buffer,
      uint16_t y,
      const char* label,
      const char* confirmation_line_one,
      const char* confirmation_line_two,
      uint16_t background,
      uint16_t accent);
  void drawTextAt(
      uint16_t* row_buffer,
      uint16_t y,
      uint16_t text_y,
      const char* text,
      uint16_t foreground,
      uint8_t scale);
  static String displaySummary(const String& summary);
  static void splitSummary(const String& summary, String& first, String& second);
  static uint16_t colorForState(const String& state);
  static const uint8_t* glyph(char character);

  esp_lcd_panel_io_handle_t io_ = nullptr;
  esp_lcd_panel_handle_t panel_ = nullptr;
  // The LCD transport may still own the row passed to draw_bitmap after the
  // call returns. Alternate two internal-RAM buffers so rendering the next
  // row never mutates a DMA transfer in flight.
  uint16_t row_buffers_[2][kWidth] = {};
  String last_state_;
  String last_caption_;
  String last_confirmation_id_;
  bool ready_ = false;
};

}  // namespace pipa
