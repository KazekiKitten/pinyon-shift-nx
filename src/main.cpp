// Pinyon Shift - native ReXGlue host

#include "pinyon_shift_init.h"

#include "pinyon_shift_app.h"

REX_DEFINE_APP(pinyon_shift, PinyonShiftApp::Create)

#if defined(_WIN32)
#include <cstdint>
// NVIDIA Optimus and AMD switchable graphics start the process on the
// discrete GPU when the executable exports these. The drivers read only the
// executable's exports; the SDK's copies in rexgpu-fh1.dll are not seen, so
// laptops ran on the integrated GPU (#534).
extern "C" {
__declspec(dllexport) uint32_t NvOptimusEnablement = 0x00000001;
__declspec(dllexport) uint32_t AmdPowerXpressRequestHighPerformance = 1;
}
#endif
