#include "pipa_display.h"

#include "pipa_display_text.h"

#include <driver/spi_master.h>
#include <esp_check.h>
#include <esp_lcd_io_spi.h>
#include <esp_lcd_panel_io.h>
#include <esp_lcd_panel_ops.h>
#include <esp_lcd_panel_vendor.h>
#include <esp_log.h>

#include "board_pins.h"
#include "vendor/esp_lcd_st77916.h"

namespace pipa {
namespace {

constexpr char kTag[] = "pipa_display";
constexpr uint32_t kSpiClockHz = 80U * 1000U * 1000U;
constexpr size_t kMaxTransferBytes = PipaDisplay::kWidth * sizeof(uint16_t);
constexpr uint16_t kBlack = 0x0000;
constexpr uint16_t kWhite = 0xFFFF;
constexpr uint16_t kBlue = 0x2D9F;
constexpr uint16_t kOrange = 0xFBE0;
constexpr uint16_t kRed = 0xF800;
constexpr uint16_t kGreen = 0x07E0;
constexpr uint16_t kPurple = 0xA81F;
constexpr uint16_t kSlate = 0x39C7;
constexpr uint16_t kFace = 0xFFE0;
constexpr uint8_t kTextScale = 3;

static const st77916_lcd_init_cmd_t vendor_specific_init_new[] = {
  {0xF0, (uint8_t []){0x28}, 1, 0},
  {0xF2, (uint8_t []){0x28}, 1, 0},
  {0x73, (uint8_t []){0xF0}, 1, 0},
  {0x7C, (uint8_t []){0xD1}, 1, 0},
  {0x83, (uint8_t []){0xE0}, 1, 0},
  {0x84, (uint8_t []){0x61}, 1, 0},
  {0xF2, (uint8_t []){0x82}, 1, 0},
  {0xF0, (uint8_t []){0x00}, 1, 0},
  {0xF0, (uint8_t []){0x01}, 1, 0},
  {0xF1, (uint8_t []){0x01}, 1, 0},
  {0xB0, (uint8_t []){0x56}, 1, 0},
  {0xB1, (uint8_t []){0x4D}, 1, 0},
  {0xB2, (uint8_t []){0x24}, 1, 0},
  {0xB4, (uint8_t []){0x87}, 1, 0},
  {0xB5, (uint8_t []){0x44}, 1, 0},
  {0xB6, (uint8_t []){0x8B}, 1, 0},
  {0xB7, (uint8_t []){0x40}, 1, 0},
  {0xB8, (uint8_t []){0x86}, 1, 0},
  {0xBA, (uint8_t []){0x00}, 1, 0},
  {0xBB, (uint8_t []){0x08}, 1, 0},
  {0xBC, (uint8_t []){0x08}, 1, 0},
  {0xBD, (uint8_t []){0x00}, 1, 0},
  {0xC0, (uint8_t []){0x80}, 1, 0},
  {0xC1, (uint8_t []){0x10}, 1, 0},
  {0xC2, (uint8_t []){0x37}, 1, 0},
  {0xC3, (uint8_t []){0x80}, 1, 0},
  {0xC4, (uint8_t []){0x10}, 1, 0},
  {0xC5, (uint8_t []){0x37}, 1, 0},
  {0xC6, (uint8_t []){0xA9}, 1, 0},
  {0xC7, (uint8_t []){0x41}, 1, 0},
  {0xC8, (uint8_t []){0x01}, 1, 0},
  {0xC9, (uint8_t []){0xA9}, 1, 0},
  {0xCA, (uint8_t []){0x41}, 1, 0},
  {0xCB, (uint8_t []){0x01}, 1, 0},
  {0xD0, (uint8_t []){0x91}, 1, 0},
  {0xD1, (uint8_t []){0x68}, 1, 0},
  {0xD2, (uint8_t []){0x68}, 1, 0},
  {0xF5, (uint8_t []){0x00, 0xA5}, 2, 0},
  {0xDD, (uint8_t []){0x4F}, 1, 0},
  {0xDE, (uint8_t []){0x4F}, 1, 0},
  {0xF1, (uint8_t []){0x10}, 1, 0},
  {0xF0, (uint8_t []){0x00}, 1, 0},
  {0xF0, (uint8_t []){0x02}, 1, 0},
  {0xE0, (uint8_t []){0xF0, 0x0A, 0x10, 0x09, 0x09, 0x36, 0x35, 0x33, 0x4A, 0x29, 0x15, 0x15, 0x2E, 0x34}, 14, 0},
  {0xE1, (uint8_t []){0xF0, 0x0A, 0x0F, 0x08, 0x08, 0x05, 0x34, 0x33, 0x4A, 0x39, 0x15, 0x15, 0x2D, 0x33}, 14, 0},
  {0xF0, (uint8_t []){0x10}, 1, 0},
  {0xF3, (uint8_t []){0x10}, 1, 0},
  {0xE0, (uint8_t []){0x07}, 1, 0},
  {0xE1, (uint8_t []){0x00}, 1, 0},
  {0xE2, (uint8_t []){0x00}, 1, 0},
  {0xE3, (uint8_t []){0x00}, 1, 0},
  {0xE4, (uint8_t []){0xE0}, 1, 0},
  {0xE5, (uint8_t []){0x06}, 1, 0},
  {0xE6, (uint8_t []){0x21}, 1, 0},
  {0xE7, (uint8_t []){0x01}, 1, 0},
  {0xE8, (uint8_t []){0x05}, 1, 0},
  {0xE9, (uint8_t []){0x02}, 1, 0},
  {0xEA, (uint8_t []){0xDA}, 1, 0},
  {0xEB, (uint8_t []){0x00}, 1, 0},
  {0xEC, (uint8_t []){0x00}, 1, 0},
  {0xED, (uint8_t []){0x0F}, 1, 0},
  {0xEE, (uint8_t []){0x00}, 1, 0},
  {0xEF, (uint8_t []){0x00}, 1, 0},
  {0xF8, (uint8_t []){0x00}, 1, 0},
  {0xF9, (uint8_t []){0x00}, 1, 0},
  {0xFA, (uint8_t []){0x00}, 1, 0},
  {0xFB, (uint8_t []){0x00}, 1, 0},
  {0xFC, (uint8_t []){0x00}, 1, 0},
  {0xFD, (uint8_t []){0x00}, 1, 0},
  {0xFE, (uint8_t []){0x00}, 1, 0},
  {0xFF, (uint8_t []){0x00}, 1, 0},
  {0x60, (uint8_t []){0x40}, 1, 0},
  {0x61, (uint8_t []){0x04}, 1, 0},
  {0x62, (uint8_t []){0x00}, 1, 0},
  {0x63, (uint8_t []){0x42}, 1, 0},
  {0x64, (uint8_t []){0xD9}, 1, 0},
  {0x65, (uint8_t []){0x00}, 1, 0},
  {0x66, (uint8_t []){0x00}, 1, 0},
  {0x67, (uint8_t []){0x00}, 1, 0},
  {0x68, (uint8_t []){0x00}, 1, 0},
  {0x69, (uint8_t []){0x00}, 1, 0},
  {0x6A, (uint8_t []){0x00}, 1, 0},
  {0x6B, (uint8_t []){0x00}, 1, 0},
  {0x70, (uint8_t []){0x40}, 1, 0},
  {0x71, (uint8_t []){0x03}, 1, 0},
  {0x72, (uint8_t []){0x00}, 1, 0},
  {0x73, (uint8_t []){0x42}, 1, 0},
  {0x74, (uint8_t []){0xD8}, 1, 0},
  {0x75, (uint8_t []){0x00}, 1, 0},
  {0x76, (uint8_t []){0x00}, 1, 0},
  {0x77, (uint8_t []){0x00}, 1, 0},
  {0x78, (uint8_t []){0x00}, 1, 0},
  {0x79, (uint8_t []){0x00}, 1, 0},
  {0x7A, (uint8_t []){0x00}, 1, 0},
  {0x7B, (uint8_t []){0x00}, 1, 0},
  {0x80, (uint8_t []){0x48}, 1, 0},
  {0x81, (uint8_t []){0x00}, 1, 0},
  {0x82, (uint8_t []){0x06}, 1, 0},
  {0x83, (uint8_t []){0x02}, 1, 0},
  {0x84, (uint8_t []){0xD6}, 1, 0},
  {0x85, (uint8_t []){0x04}, 1, 0},
  {0x86, (uint8_t []){0x00}, 1, 0},
  {0x87, (uint8_t []){0x00}, 1, 0},
  {0x88, (uint8_t []){0x48}, 1, 0},
  {0x89, (uint8_t []){0x00}, 1, 0},
  {0x8A, (uint8_t []){0x08}, 1, 0},
  {0x8B, (uint8_t []){0x02}, 1, 0},
  {0x8C, (uint8_t []){0xD8}, 1, 0},
  {0x8D, (uint8_t []){0x04}, 1, 0},
  {0x8E, (uint8_t []){0x00}, 1, 0},
  {0x8F, (uint8_t []){0x00}, 1, 0},
  {0x90, (uint8_t []){0x48}, 1, 0},
  {0x91, (uint8_t []){0x00}, 1, 0},
  {0x92, (uint8_t []){0x0A}, 1, 0},
  {0x93, (uint8_t []){0x02}, 1, 0},
  {0x94, (uint8_t []){0xDA}, 1, 0},
  {0x95, (uint8_t []){0x04}, 1, 0},
  {0x96, (uint8_t []){0x00}, 1, 0},
  {0x97, (uint8_t []){0x00}, 1, 0},
  {0x98, (uint8_t []){0x48}, 1, 0},
  {0x99, (uint8_t []){0x00}, 1, 0},
  {0x9A, (uint8_t []){0x0C}, 1, 0},
  {0x9B, (uint8_t []){0x02}, 1, 0},
  {0x9C, (uint8_t []){0xDC}, 1, 0},
  {0x9D, (uint8_t []){0x04}, 1, 0},
  {0x9E, (uint8_t []){0x00}, 1, 0},
  {0x9F, (uint8_t []){0x00}, 1, 0},
  {0xA0, (uint8_t []){0x48}, 1, 0},
  {0xA1, (uint8_t []){0x00}, 1, 0},
  {0xA2, (uint8_t []){0x05}, 1, 0},
  {0xA3, (uint8_t []){0x02}, 1, 0},
  {0xA4, (uint8_t []){0xD5}, 1, 0},
  {0xA5, (uint8_t []){0x04}, 1, 0},
  {0xA6, (uint8_t []){0x00}, 1, 0},
  {0xA7, (uint8_t []){0x00}, 1, 0},
  {0xA8, (uint8_t []){0x48}, 1, 0},
  {0xA9, (uint8_t []){0x00}, 1, 0},
  {0xAA, (uint8_t []){0x07}, 1, 0},
  {0xAB, (uint8_t []){0x02}, 1, 0},
  {0xAC, (uint8_t []){0xD7}, 1, 0},
  {0xAD, (uint8_t []){0x04}, 1, 0},
  {0xAE, (uint8_t []){0x00}, 1, 0},
  {0xAF, (uint8_t []){0x00}, 1, 0},
  {0xB0, (uint8_t []){0x48}, 1, 0},
  {0xB1, (uint8_t []){0x00}, 1, 0},
  {0xB2, (uint8_t []){0x09}, 1, 0},
  {0xB3, (uint8_t []){0x02}, 1, 0},
  {0xB4, (uint8_t []){0xD9}, 1, 0},
  {0xB5, (uint8_t []){0x04}, 1, 0},
  {0xB6, (uint8_t []){0x00}, 1, 0},
  {0xB7, (uint8_t []){0x00}, 1, 0},

  {0xB8, (uint8_t []){0x48}, 1, 0},
  {0xB9, (uint8_t []){0x00}, 1, 0},
  {0xBA, (uint8_t []){0x0B}, 1, 0},
  {0xBB, (uint8_t []){0x02}, 1, 0},
  {0xBC, (uint8_t []){0xDB}, 1, 0},
  {0xBD, (uint8_t []){0x04}, 1, 0},
  {0xBE, (uint8_t []){0x00}, 1, 0},
  {0xBF, (uint8_t []){0x00}, 1, 0},
  {0xC0, (uint8_t []){0x10}, 1, 0},
  {0xC1, (uint8_t []){0x47}, 1, 0},
  {0xC2, (uint8_t []){0x56}, 1, 0},
  {0xC3, (uint8_t []){0x65}, 1, 0},
  {0xC4, (uint8_t []){0x74}, 1, 0},
  {0xC5, (uint8_t []){0x88}, 1, 0},
  {0xC6, (uint8_t []){0x99}, 1, 0},
  {0xC7, (uint8_t []){0x01}, 1, 0},
  {0xC8, (uint8_t []){0xBB}, 1, 0},
  {0xC9, (uint8_t []){0xAA}, 1, 0},
  {0xD0, (uint8_t []){0x10}, 1, 0},
  {0xD1, (uint8_t []){0x47}, 1, 0},
  {0xD2, (uint8_t []){0x56}, 1, 0},
  {0xD3, (uint8_t []){0x65}, 1, 0},
  {0xD4, (uint8_t []){0x74}, 1, 0},
  {0xD5, (uint8_t []){0x88}, 1, 0},
  {0xD6, (uint8_t []){0x99}, 1, 0},
  {0xD7, (uint8_t []){0x01}, 1, 0},
  {0xD8, (uint8_t []){0xBB}, 1, 0},
  {0xD9, (uint8_t []){0xAA}, 1, 0},
  {0xF3, (uint8_t []){0x01}, 1, 0},
  {0xF0, (uint8_t []){0x00}, 1, 0},
  {0x21, (uint8_t []){0x00}, 1, 0},
  {0x11, (uint8_t []){0x00}, 1, 120},
  {0x29, (uint8_t []){0x00}, 1, 0},
};

static const uint8_t kFont[26][5] = {
    {0x7E, 0x11, 0x11, 0x11, 0x7E},  // A
    {0x7F, 0x49, 0x49, 0x49, 0x36},  // B
    {0x3E, 0x41, 0x41, 0x41, 0x22},  // C
    {0x7F, 0x41, 0x41, 0x22, 0x1C},  // D
    {0x7F, 0x49, 0x49, 0x49, 0x41},  // E
    {0x7F, 0x09, 0x09, 0x09, 0x01},  // F
    {0x3E, 0x41, 0x49, 0x49, 0x7A},  // G
    {0x7F, 0x08, 0x08, 0x08, 0x7F},  // H
    {0x00, 0x41, 0x7F, 0x41, 0x00},  // I
    {0x20, 0x40, 0x41, 0x3F, 0x01},  // J
    {0x7F, 0x08, 0x14, 0x22, 0x41},  // K
    {0x7F, 0x40, 0x40, 0x40, 0x40},  // L
    {0x7F, 0x02, 0x0C, 0x02, 0x7F},  // M
    {0x7F, 0x04, 0x08, 0x10, 0x7F},  // N
    {0x3E, 0x41, 0x41, 0x41, 0x3E},  // O
    {0x7F, 0x09, 0x09, 0x09, 0x06},  // P
    {0x3E, 0x41, 0x51, 0x21, 0x5E},  // Q
    {0x7F, 0x09, 0x19, 0x29, 0x46},  // R
    {0x46, 0x49, 0x49, 0x49, 0x31},  // S
    {0x01, 0x01, 0x7F, 0x01, 0x01},  // T
    {0x3F, 0x40, 0x40, 0x40, 0x3F},  // U
    {0x1F, 0x20, 0x40, 0x20, 0x1F},  // V
    {0x7F, 0x20, 0x18, 0x20, 0x7F},  // W
    {0x63, 0x14, 0x08, 0x14, 0x63},  // X
    {0x07, 0x08, 0x70, 0x08, 0x07},  // Y
    {0x61, 0x51, 0x49, 0x45, 0x43},  // Z
};

}  // namespace

bool PipaDisplay::begin(Tca9554* io_expander) {
  if (ready_) return true;
  if (io_expander == nullptr) {
    ESP_LOGW(kTag, "display reset requires the TCA9554 expander");
    return false;
  }
  if (!io_expander->setOutput(Tca9554::kDisplayReset, false)) return false;
  delay(10);
  if (!io_expander->setOutput(Tca9554::kDisplayReset, true)) return false;
  delay(10);

  spi_bus_config_t bus_config = {};
  bus_config.sclk_io_num = pipa::board::kDisplaySck;
  bus_config.data0_io_num = pipa::board::kDisplayData0;
  bus_config.data1_io_num = pipa::board::kDisplayData1;
  bus_config.data2_io_num = pipa::board::kDisplayData2;
  bus_config.data3_io_num = pipa::board::kDisplayData3;
  bus_config.data4_io_num = -1;
  bus_config.data5_io_num = -1;
  bus_config.data6_io_num = -1;
  bus_config.data7_io_num = -1;
  bus_config.max_transfer_sz = kMaxTransferBytes;
  bus_config.flags = SPICOMMON_BUSFLAG_MASTER;
  bus_config.intr_flags = 0;
  if (spi_bus_initialize(SPI2_HOST, &bus_config, SPI_DMA_CH_AUTO) != ESP_OK) {
    ESP_LOGE(kTag, "SPI2 initialization failed");
    return false;
  }

  auto cleanup = [this]() {
    if (panel_ != nullptr) {
      esp_lcd_panel_del(panel_);
      panel_ = nullptr;
    }
    if (io_ != nullptr) {
      esp_lcd_panel_io_del(io_);
      io_ = nullptr;
    }
    spi_bus_free(SPI2_HOST);
  };

  esp_lcd_panel_io_spi_config_t io_config = {};
  io_config.cs_gpio_num = pipa::board::kDisplayCs;
  io_config.dc_gpio_num = -1;
  io_config.spi_mode = 0;
  io_config.pclk_hz = kSpiClockHz;
  io_config.trans_queue_depth = 1;
  io_config.lcd_cmd_bits = 32;
  io_config.lcd_param_bits = 8;
  io_config.flags.quad_mode = 1;
  io_config.flags.sio_mode = 0;
  io_config.flags.lsb_first = 0;
  io_config.flags.cs_high_active = 0;

  if (esp_lcd_new_panel_io_spi(SPI2_HOST, &io_config, &io_) != ESP_OK) {
    ESP_LOGE(kTag, "LCD panel IO initialization failed");
    cleanup();
    return false;
  }

  st77916_vendor_config_t vendor_config = {};
  vendor_config.flags.use_qspi_interface = 1;
  vendor_config.init_cmds = vendor_specific_init_new;
  vendor_config.init_cmds_size = sizeof(vendor_specific_init_new) / sizeof(vendor_specific_init_new[0]);

  esp_lcd_panel_dev_config_t panel_config = {};
  panel_config.reset_gpio_num = -1;
  panel_config.color_space = ESP_LCD_COLOR_SPACE_RGB;
  panel_config.data_endian = LCD_RGB_DATA_ENDIAN_BIG;
  panel_config.bits_per_pixel = 16;
  panel_config.flags.reset_active_high = 0;
  panel_config.vendor_config = &vendor_config;

  if (esp_lcd_new_panel_st77916(io_, &panel_config, &panel_) != ESP_OK ||
      esp_lcd_panel_reset(panel_) != ESP_OK ||
      esp_lcd_panel_init(panel_) != ESP_OK ||
      esp_lcd_panel_disp_on_off(panel_, true) != ESP_OK) {
    ESP_LOGE(kTag, "ST77916 panel initialization failed");
    cleanup();
    return false;
  }

  if (!ledcAttach(pipa::board::kDisplayBacklight, 20000, 10)) {
    ESP_LOGE(kTag, "backlight PWM initialization failed");
    cleanup();
    return false;
  }
  ledcWrite(pipa::board::kDisplayBacklight, 512);
  ready_ = true;
  return true;
}

void PipaDisplay::render(const UiSnapshot& snapshot) {
  if (!ready_ ||
      (snapshot.state == last_state_ && snapshot.caption == last_caption_ &&
       snapshot.confirmation_id == last_confirmation_id_)) {
    return;
  }

  const uint16_t background = colorForState(snapshot.state);
  const uint16_t accent = snapshot.state == "confirm" ? kRed : kWhite;
  const char* label = "IDLE";
  if (snapshot.state == "listening") label = "LISTEN";
  else if (snapshot.state == "thinking") label = "THINK";
  else if (snapshot.state == "confirm") label = "CONFIRM";
  else if (snapshot.state == "speaking") label = "SPEAK";
  else if (snapshot.state == "focus") label = "FOCUS";
  else if (snapshot.state == "dashboard") label = "HOME";

  String summary = displaySummary(
      snapshot.state == "confirm" ? snapshot.confirmation_summary : snapshot.caption);
  String summary_line_one;
  String summary_line_two;
  splitSummary(summary, summary_line_one, summary_line_two);
  for (uint16_t y = 0; y < kHeight; ++y) {
    uint16_t* row_buffer = row_buffers_[y % 2];
    drawRow(
        row_buffer,
        y,
        label,
        summary_line_one.c_str(),
        summary_line_two.c_str(),
        background,
        accent);
    if (esp_lcd_panel_draw_bitmap(panel_, 0, y, kWidth, y + 1, row_buffer) != ESP_OK) {
      ESP_LOGE(kTag, "LCD row transfer failed");
      ready_ = false;
      return;
    }
  }
  last_state_ = snapshot.state;
  last_caption_ = snapshot.caption;
  last_confirmation_id_ = snapshot.confirmation_id;
}

void PipaDisplay::drawRow(
    uint16_t* row_buffer,
    uint16_t y,
    const char* label,
    const char* confirmation_line_one,
    const char* confirmation_line_two,
    uint16_t background,
    uint16_t accent) {
  for (uint16_t x = 0; x < kWidth; ++x) row_buffer[x] = background;

  const int32_t center = kWidth / 2;
  const int32_t dy = static_cast<int32_t>(y) - center;
  const bool idle_face = strcmp(label, "IDLE") == 0 && confirmation_line_one[0] == '\0';
  if (idle_face) {
    constexpr int32_t kFaceRadius = 112;
    constexpr int32_t kEyeRadius = 9;
    constexpr int32_t kEyeY = 148;
    const int32_t distance = dy * dy;
    for (uint16_t x = 0; x < kWidth; ++x) {
      const int32_t dx = static_cast<int32_t>(x) - center;
      const int32_t squared = dx * dx + distance;
      if (squared <= kFaceRadius * kFaceRadius) row_buffer[x] = kFace;

      const int32_t left_eye_dx = static_cast<int32_t>(x) - 142;
      const int32_t right_eye_dx = static_cast<int32_t>(x) - 218;
      const int32_t eye_dy = static_cast<int32_t>(y) - kEyeY;
      if ((left_eye_dx * left_eye_dx + eye_dy * eye_dy <= kEyeRadius * kEyeRadius) ||
          (right_eye_dx * right_eye_dx + eye_dy * eye_dy <= kEyeRadius * kEyeRadius)) {
        row_buffer[x] = kBlack;
      }

      if (dx >= -55 && dx <= 55) {
        const int32_t mouth_y = 232 - (dx * dx) / 120;
        const int32_t mouth_delta = static_cast<int32_t>(y) - mouth_y;
        if (mouth_delta >= -3 && mouth_delta <= 3) row_buffer[x] = kBlack;
      }
    }
  } else {
    const int32_t outer_radius = 142;
    const int32_t inner_radius = 128;
    const int32_t distance = dy * dy;
    for (uint16_t x = 0; x < kWidth; ++x) {
      const int32_t dx = static_cast<int32_t>(x) - center;
      const int32_t squared = dx * dx + distance;
      if (squared <= outer_radius * outer_radius && squared >= inner_radius * inner_radius) {
        row_buffer[x] = accent;
      }
    }
  }

  const uint16_t text_y = 142;
  if (!idle_face && y >= text_y && y < text_y + 7 * kTextScale) {
    drawTextAt(row_buffer, y, text_y, label, kWhite, kTextScale);
  }
  if (strcmp(label, "CONFIRM") == 0) {
    if (confirmation_line_one[0] != '\0') {
      drawTextAt(row_buffer, y, 194, confirmation_line_one, kWhite, 2);
    }
    if (confirmation_line_two[0] != '\0') {
      drawTextAt(row_buffer, y, 212, confirmation_line_two, kWhite, 2);
    }
    drawTextAt(row_buffer, y, 252, "TAP", kWhite, 3);
  } else if (confirmation_line_one[0] != '\0') {
    drawTextAt(row_buffer, y, 194, confirmation_line_one, kWhite, 2);
    if (confirmation_line_two[0] != '\0') {
      drawTextAt(row_buffer, y, 212, confirmation_line_two, kWhite, 2);
    }
  }
}

void PipaDisplay::drawTextAt(
    uint16_t* row_buffer,
    uint16_t y,
    uint16_t text_y,
    const char* text,
    uint16_t foreground,
    uint8_t scale) {
  const uint16_t text_width = static_cast<uint16_t>(strlen(text) * 6 * scale);
  const int32_t start_x = (static_cast<int32_t>(kWidth) - text_width) / 2;
  if (y < text_y || y >= text_y + 7 * scale) return;
  const uint8_t glyph_row = static_cast<uint8_t>((y - text_y) / scale);
  int32_t cursor = start_x;
  for (size_t index = 0; text[index] != '\0'; ++index) {
    const uint8_t* bitmap = glyph(text[index]);
    for (uint8_t column = 0; column < 5; ++column) {
      for (uint8_t bit = 0; bit < 7; ++bit) {
        if ((bitmap[column] & (1U << bit)) != 0 && glyph_row == bit) {
          for (uint8_t pixel = 0; pixel < scale; ++pixel) {
            const int32_t x = cursor + column * scale + pixel;
            if (x >= 0 && x < kWidth) row_buffer[x] = foreground;
          }
        }
      }
    }
    cursor += 6 * scale;
  }
}

String PipaDisplay::displaySummary(const String& summary) {
  const std::string normalized = display_text::normalizeSummary(summary.c_str());
  return String(normalized.c_str());
}

void PipaDisplay::splitSummary(const String& summary, String& first, String& second) {
  std::string first_text;
  std::string second_text;
  display_text::splitSummary(summary.c_str(), first_text, second_text);
  first = first_text.c_str();
  second = second_text.c_str();
}

uint16_t PipaDisplay::colorForState(const String& state) {
  if (state == "listening") return kBlue;
  if (state == "thinking") return kOrange;
  if (state == "confirm") return 0x4208;
  if (state == "speaking") return kGreen;
  if (state == "focus") return kPurple;
  if (state == "dashboard") return kSlate;
  return kBlack;
}

const uint8_t* PipaDisplay::glyph(char character) {
  static const uint8_t empty[5] = {0, 0, 0, 0, 0};
  if (character >= 'a' && character <= 'z') character = static_cast<char>(character - 'a' + 'A');
  if (character < 'A' || character > 'Z') return empty;
  return kFont[character - 'A'];
}

}  // namespace pipa
