/**
* @copyright 2024 - Max Bebök
* @license MIT
*/
#include "renderer/particles/ptxSystem.h"
#include "lib/matrixManager.h"
#include "debug/profiler.h"

P64::PTX::System::System(Type ptxType, uint32_t maxSize)
  : countMax{maxSize}, count{0}, type{ptxType}
{
  assert(sizeof(countMax) % 2 == 0);
  if(countMax > 0) {
    const std::size_t pairCount = (countMax + 1U) / 2U;
    const std::size_t pairSize = (type == COLOR_A_S16 || type == TEX_A_S16)
      ? sizeof(TPXParticleS16)
      : sizeof(TPXParticleS8);
    const std::size_t allocSize = pairCount * pairSize;
    particles = malloc_uncached(allocSize);
    sys_hw_memset(particles, 0, allocSize);
  }
}

P64::PTX::System::~System() {
  if(particles) {
    free_uncached(particles);
  }
}

void P64::PTX::System::draw() const {
  if(count == 0)return;
  Profiler::recordParticles(count);

  uint32_t safeCount = count;
  if(safeCount % 2 != 0) {
    if(type == COLOR_A_S16 || type == TEX_A_S16) {
      *tpx_buffer_s16_get_size((TPXParticleS16*)particles, count) = 0;
    } else {
      *tpx_buffer_s8_get_size((TPXParticleS8*)particles, count) = 0;
    }
    ++safeCount;
  }

  switch(type)
  {
    case COLOR_RGBA_S8: tpx_particle_draw_s8((TPXParticleS8*)particles, safeCount); break;
    case TEX_RGBA_S8: tpx_particle_draw_tex_s8((TPXParticleS8*)particles, safeCount); break;
    case COLOR_A_S16: tpx_particle_draw_s16((TPXParticleS16*)particles, safeCount); break;
    case TEX_A_S16: tpx_particle_draw_tex_s16((TPXParticleS16*)particles, safeCount); break;
  }
}
