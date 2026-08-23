#include "pipa_local_wake.h"

#include "pipa_device_config.h"

#if PIPA_LOCAL_WAKE_PHRASE_ENABLED
#include <esp_err.h>
#include <esp_heap_caps.h>
#include <new>
#include <string.h>

extern "C" {
#include "esp_mn_models.h"
#include "esp_mn_speech_commands.h"
#include "flite_g2p.h"
#include "model_path.h"
}
#endif

namespace pipa {

#if PIPA_LOCAL_WAKE_PHRASE_ENABLED
namespace {

constexpr int kWakeCommandId = 1;
constexpr int kRecognitionWindowMs = 5000;
constexpr size_t kMaximumModelFrameSamples = 1024;

// MultiNet's acoustic model is English. These spellings produce several
// close English-phoneme renderings of the Spanish phrase without changing
// the phrase shown to the user or sending room audio to the PC.
constexpr const char* kWakePhraseVariants[] = {
    "peepa may escoochas",
    "peepa meh escoochas",
    "peepa may escoochahs",
    "peepa meh escoochahs",
    "peepa may ess coo chahs",
    "peepa meh ess coo chahs",
    "pipa me escuchas",
};

}  // namespace

struct PipaLocalWakePhrase::Impl {
  srmodel_list_t* models = nullptr;
  esp_mn_iface_t* multinet = nullptr;
  model_iface_data_t* model_data = nullptr;
  int16_t* frame = nullptr;
  size_t frame_samples = 0;
  size_t frame_used = 0;
};
#else
struct PipaLocalWakePhrase::Impl {};
#endif

bool PipaLocalWakePhrase::begin() {
#if PIPA_LOCAL_WAKE_PHRASE_ENABLED
  if (ready_) return true;
  impl_ = new (std::nothrow) Impl();
  if (impl_ == nullptr) return false;

  impl_->models = esp_srmodel_init("model");
  if (impl_->models == nullptr) return false;
  char* model_name = esp_srmodel_filter(impl_->models, ESP_MN_PREFIX, ESP_MN_ENGLISH);
  if (model_name == nullptr) return false;
  impl_->multinet = esp_mn_handle_from_name(model_name);
  if (impl_->multinet == nullptr) return false;
  impl_->model_data = impl_->multinet->create(model_name, kRecognitionWindowMs);
  if (impl_->model_data == nullptr ||
      esp_mn_commands_alloc(impl_->multinet, impl_->model_data) != ESP_OK) {
    return false;
  }

  for (const char* variant : kWakePhraseVariants) {
    char* phonemes = flite_g2p(variant, 1);
    if (phonemes == nullptr ||
        esp_mn_commands_phoneme_add(kWakeCommandId, variant, phonemes) != ESP_OK) {
      free(phonemes);
      return false;
    }
    free(phonemes);
  }
  if (esp_mn_commands_update() != nullptr) return false;

  const int model_frame_samples = impl_->multinet->get_samp_chunksize(impl_->model_data);
  if (model_frame_samples <= 0 ||
      static_cast<size_t>(model_frame_samples) > kMaximumModelFrameSamples ||
      impl_->multinet->get_samp_rate(impl_->model_data) != 16000) {
    return false;
  }
  impl_->frame_samples = static_cast<size_t>(model_frame_samples);
  impl_->frame = static_cast<int16_t*>(heap_caps_calloc(
      impl_->frame_samples,
      sizeof(int16_t),
      MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
  ready_ = impl_->frame != nullptr;
  return ready_;
#else
  return false;
#endif
}

bool PipaLocalWakePhrase::process(const int16_t* samples, size_t sample_count) {
#if PIPA_LOCAL_WAKE_PHRASE_ENABLED
  if (!ready_ || impl_ == nullptr || samples == nullptr) return false;
  while (sample_count > 0) {
    const size_t available = impl_->frame_samples - impl_->frame_used;
    const size_t copied = sample_count < available ? sample_count : available;
    memcpy(impl_->frame + impl_->frame_used, samples, copied * sizeof(int16_t));
    impl_->frame_used += copied;
    samples += copied;
    sample_count -= copied;
    if (impl_->frame_used != impl_->frame_samples) continue;

    const esp_mn_state_t state = impl_->multinet->detect(impl_->model_data, impl_->frame);
    memset(impl_->frame, 0, impl_->frame_samples * sizeof(int16_t));
    impl_->frame_used = 0;
    if (state == ESP_MN_STATE_TIMEOUT) {
      impl_->multinet->clean(impl_->model_data);
      continue;
    }
    if (state != ESP_MN_STATE_DETECTED) continue;
    const esp_mn_results_t* results = impl_->multinet->get_results(impl_->model_data);
    const bool detected = results != nullptr && results->num > 0 &&
        results->command_id[0] == kWakeCommandId;
    impl_->multinet->clean(impl_->model_data);
    if (detected) return true;
  }
#else
  (void)samples;
  (void)sample_count;
#endif
  return false;
}

void PipaLocalWakePhrase::reset() {
#if PIPA_LOCAL_WAKE_PHRASE_ENABLED
  if (!ready_ || impl_ == nullptr) return;
  if (impl_->frame != nullptr) {
    memset(impl_->frame, 0, impl_->frame_samples * sizeof(int16_t));
  }
  impl_->frame_used = 0;
  impl_->multinet->clean(impl_->model_data);
#endif
}

}  // namespace pipa
