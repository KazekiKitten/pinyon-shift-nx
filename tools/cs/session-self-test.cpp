// Link against the probe's real rexruntime; no game needed. Separate process
// per mode so the same lazy initialization and exclusive-create path are used.
#include <rex/session_probe.h>
#include <array>
#include <cassert>
#include <cstdlib>
#include <string>

int32_t& FLAGS_cs_session_mode_storage_();
std::string& FLAGS_cs_session_path_storage_();
namespace rex { void InitLoggingEarly(); }

int main(int argc, char** argv) {
  if (argc < 3) return 2;
  rex::InitLoggingEarly();
  int mode = std::atoi(argv[1]);
  FLAGS_cs_session_mode_storage_() = mode;
  FLAGS_cs_session_path_storage_() = argv[2];
  using namespace rex::session_probe;
  SetThreadTag(7);
  auto value = Scalar(Kind::kTimebase, 9, mode == 2 ? 999 : 123, true);
  assert(value == 123);
  std::array<uint8_t, 16> input;
  input.fill(mode == 2 ? 0xAA : 0x55);
  Blob(Kind::kInputState, 0, input.data(), input.size());
  for (auto b : input) assert(b == 0x55);
  const bool wrong_hash = argc > 3 && std::string(argv[3]) == "hash";
  Scalar(Kind::kSyncRequest, argc > 3 && !wrong_hash ? 21 : 20, 7);
  Scalar(Kind::kPm4Frame, 1, wrong_hash ? 0xABCDEE : 0xABCDEF);
  Flush();
  return 0;
}
