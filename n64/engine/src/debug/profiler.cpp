/**
 * @copyright 2026 - Binface64 contributors
 * @license MIT
 */
#include "debug/profiler.h"

#include <algorithm>
#include <cmath>
#include <libdragon.h>

#include "lib/memory.h"
#include "../audio/audioManagerPrivate.h"

extern "C" {
  extern int __heap_top_allocated_size;
}

namespace
{
  constexpr uint32_t MAX_SAMPLES = 2048;
  constexpr uint32_t STACK_RESERVED_BYTES = 0x10000;

  P64::Profiler::Config config{};
  float frameTimesMs[MAX_SAMPLES]{};
  float pendingFrameTimeMs{};
  uint32_t frameIndex{};
  uint32_t sampleCount{};
  bool emitted{};

  uint32_t frameTriangles{};
  uint32_t frameDrawCalls{};
  uint32_t frameMaterialChanges{};
  const T3DMaterial *lastMaterial{};

  uint64_t triangleTotal{};
  uint64_t drawCallTotal{};
  uint64_t materialChangeTotal{};
  uint64_t voiceTotal{};
  double fpsTotal{};
  uint32_t trianglePeak{};
  uint32_t drawCallPeak{};
  uint32_t materialChangePeak{};
  uint32_t voicePeak{};
  uint32_t peakHeapUsed{};
  uint32_t peakTopAllocated{};
  uint32_t peakRdramUsed{};

  bool sampling()
  {
    return config.sampleFrames > 0 && !emitted && frameIndex >= config.warmupFrames && sampleCount < config.sampleFrames;
  }

  float percentile(const float *sorted, uint32_t count, float fraction)
  {
    if(count == 0)return 0.0f;
    auto index = static_cast<uint32_t>(std::ceil(fraction * static_cast<float>(count - 1)));
    return sorted[std::min(index, count-1)];
  }

  float fpsFromMs(float milliseconds)
  {
    return milliseconds > 0.0f ? 1000.0f / milliseconds : 0.0f;
  }

  void emitProfile()
  {
    std::sort(frameTimesMs, frameTimesMs + sampleCount);
    double frameTimeTotal = 0.0;
    for(uint32_t index=0; index<sampleCount; ++index)frameTimeTotal += static_cast<double>(frameTimesMs[index]);

    const float frameP01 = percentile(frameTimesMs, sampleCount, 0.01f);
    const float frameP05 = percentile(frameTimesMs, sampleCount, 0.05f);
    const float frameP50 = percentile(frameTimesMs, sampleCount, 0.50f);
    const float frameP95 = percentile(frameTimesMs, sampleCount, 0.95f);
    const float frameP99 = percentile(frameTimesMs, sampleCount, 0.99f);
    const float frameWorst = frameTimesMs[sampleCount-1];
    const double frameAverage = frameTimeTotal / static_cast<double>(sampleCount);
    const auto staticMemory = P64::Mem::getStaticMemInfo();

    debugf(
      "BF64_PROFILE_JSON:{\"schema\":\"bf64.runtime-profile\",\"version\":1,"
      "\"target\":{\"platform\":\"n64\",\"rdram_total_bytes\":%d},"
      "\"sampling\":{\"warmup_frames\":%u,\"sample_frames\":%u},"
      "\"frame_time_ms\":{\"average\":%.3f,\"worst\":%.3f,\"p1\":%.3f,\"p5\":%.3f,\"p50\":%.3f,\"p95\":%.3f,\"p99\":%.3f},"
      "\"fps\":{\"average\":%.3f,\"worst\":%.3f,\"p1\":%.3f,\"p5\":%.3f,\"p50\":%.3f,\"p95\":%.3f,\"p99\":%.3f},"
      "\"render\":{\"triangles\":{\"total\":%llu,\"average\":%.3f,\"peak\":%u},"
      "\"draw_calls\":{\"total\":%llu,\"average\":%.3f,\"peak\":%u},"
      "\"material_changes\":{\"total\":%llu,\"average\":%.3f,\"peak\":%u}},"
      "\"memory\":{\"static_bytes\":%u,\"stack_reserved_bytes\":%u,\"peak_heap_used_bytes\":%u,\"peak_top_allocated_bytes\":%u,\"peak_rdram_used_bytes\":%u},"
      "\"audio\":{\"average_voice_count\":%.3f,\"peak_voice_count\":%u}}\n",
      get_memory_size(),
      static_cast<unsigned>(config.warmupFrames), static_cast<unsigned>(sampleCount),
      frameAverage, static_cast<double>(frameWorst), static_cast<double>(frameP01), static_cast<double>(frameP05),
      static_cast<double>(frameP50), static_cast<double>(frameP95), static_cast<double>(frameP99),
      fpsTotal / static_cast<double>(sampleCount), static_cast<double>(fpsFromMs(frameWorst)),
      static_cast<double>(fpsFromMs(frameP99)), static_cast<double>(fpsFromMs(frameP95)),
      static_cast<double>(fpsFromMs(frameP50)), static_cast<double>(fpsFromMs(frameP05)), static_cast<double>(fpsFromMs(frameP01)),
      static_cast<unsigned long long>(triangleTotal), static_cast<double>(triangleTotal) / sampleCount, static_cast<unsigned>(trianglePeak),
      static_cast<unsigned long long>(drawCallTotal), static_cast<double>(drawCallTotal) / sampleCount, static_cast<unsigned>(drawCallPeak),
      static_cast<unsigned long long>(materialChangeTotal), static_cast<double>(materialChangeTotal) / sampleCount, static_cast<unsigned>(materialChangePeak),
      static_cast<unsigned>(staticMemory.total), static_cast<unsigned>(STACK_RESERVED_BYTES), static_cast<unsigned>(peakHeapUsed),
      static_cast<unsigned>(peakTopAllocated), static_cast<unsigned>(peakRdramUsed),
      static_cast<double>(voiceTotal) / sampleCount, static_cast<unsigned>(voicePeak)
    );
    emitted = true;
  }
}

void P64::Profiler::configure(Config value)
{
  config = value;
  if(config.sampleFrames > MAX_SAMPLES)config.sampleFrames = MAX_SAMPLES;
  frameIndex = 0;
  sampleCount = 0;
  emitted = false;
  triangleTotal = drawCallTotal = materialChangeTotal = voiceTotal = 0;
  fpsTotal = 0.0;
  trianglePeak = drawCallPeak = materialChangePeak = voicePeak = 0;
  peakHeapUsed = peakTopAllocated = peakRdramUsed = 0;
  if(config.sampleFrames > 0) {
    debugf(
      "BF64 profiler armed: warmup=%u samples=%u\n",
      static_cast<unsigned>(config.warmupFrames), static_cast<unsigned>(config.sampleFrames)
    );
  }
}

bool P64::Profiler::isActive()
{
  return config.sampleFrames > 0 && !emitted;
}

void P64::Profiler::beginFrame(float deltaTime)
{
  if(!isActive())return;
  pendingFrameTimeMs = deltaTime * 1000.0f;
  frameTriangles = 0;
  frameDrawCalls = 0;
  frameMaterialChanges = 0;
  lastMaterial = nullptr;
}

void P64::Profiler::recordObject(const T3DObject *object)
{
  if(!sampling() || object == nullptr)return;
  frameTriangles += object->triCount;
  ++frameDrawCalls;
  if(object->material != lastMaterial) {
    ++frameMaterialChanges;
    lastMaterial = object->material;
  }
}

void P64::Profiler::recordModel(const T3DModel *model)
{
  if(!sampling() || model == nullptr)return;
  auto iterator = t3d_model_iter_create(model, T3D_CHUNK_TYPE_OBJECT);
  while(t3d_model_iter_next(&iterator))recordObject(iterator.object);
}

void P64::Profiler::endFrame()
{
  if(!isActive())return;
  if(sampling()) {
    frameTimesMs[sampleCount] = pendingFrameTimeMs;
    fpsTotal += static_cast<double>(fpsFromMs(pendingFrameTimeMs));
    triangleTotal += frameTriangles;
    drawCallTotal += frameDrawCalls;
    materialChangeTotal += frameMaterialChanges;
    trianglePeak = std::max(trianglePeak, frameTriangles);
    drawCallPeak = std::max(drawCallPeak, frameDrawCalls);
    materialChangePeak = std::max(materialChangePeak, frameMaterialChanges);

    heap_stats_t heap{};
    sys_get_heap_stats(&heap);
    const uint32_t topAllocated = std::max(0, __heap_top_allocated_size);
    const auto staticMemory = Mem::getStaticMemInfo();
    const uint32_t rdramUsed = staticMemory.total + STACK_RESERVED_BYTES +
      static_cast<uint32_t>(std::max(0, heap.used)) + topAllocated;
    peakHeapUsed = std::max(peakHeapUsed, static_cast<uint32_t>(std::max(0, heap.used)));
    peakTopAllocated = std::max(peakTopAllocated, topAllocated);
    peakRdramUsed = std::max(peakRdramUsed, rdramUsed);

    const auto audio = AudioManager::getMetrics();
    const uint32_t voices = static_cast<uint32_t>(__builtin_popcount(audio.maskPlaying));
    voiceTotal += voices;
    voicePeak = std::max(voicePeak, voices);
    ++sampleCount;
  }
  ++frameIndex;
  if(sampleCount == config.sampleFrames)emitProfile();
}
