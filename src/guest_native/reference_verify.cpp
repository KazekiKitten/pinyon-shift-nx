// Lockstep verify of the generator's codegen options (NEXT_LEVEL_RESEARCH.md
// NL-0.2). The generator emits every function listed in reference_functions,
// and every Nth leaf function with reference_sample_every, a second time as
// `ref_sub_X`: the reference options (every register in ctx, no folding, calls
// through the thunk) and every store routed through a log (rex/ppc/reference.h).
// The generated pinyon_shift_reference.h names them, and this file defines the
// strong `sub_X` for each, which with pinyon_shift_reference_verify=N runs the
// reference copy on a copy of the registers every Nth call, rolls its stores
// back, runs the optimized function for real, and compares the registers a
// caller may read and the bytes both wrote. Mismatches are logged with their
// inputs; the game always keeps the optimized function's results.

#include "guest_native/guest_native.h"

#include <atomic>
#include <mutex>
#include <string>
#include <vector>

#include <fmt/format.h>
#include <rex/cvar.h>
#include <rex/ppc/reference.h>

#include "pinyon_shift_diagnostics.h"

REXCVAR_DEFINE_UINT32(pinyon_shift_reference_verify, 0, "Pinyon Shift",
                      "Every Nth call of a function with a reference copy also runs the copy and "
                      "compares registers and written memory (0 = off, 1 = every call)")
    .lifecycle(rex::cvar::Lifecycle::kHotReload);

namespace pinyon_shift::guest_native::reference {
namespace {

constexpr uint64_t kMaxLoggedMismatches = 64;

struct Entry {
  const char* name;
  uint32_t address;
  std::atomic<uint64_t> calls{0};
  std::atomic<uint64_t> verified{0};
  std::atomic<uint64_t> mismatched{0};
};

std::mutex registry_mutex;
std::vector<Entry*> registry;

struct Registration {
  explicit Registration(Entry& entry) {
    std::lock_guard lock(registry_mutex);
    registry.push_back(&entry);
  }
};

std::string Hex64(uint64_t value) { return fmt::format("{:016X}", value); }

void Dispatch(Entry& entry, PPCFunc* original, PPCFunc* reference, PPCContext& ctx,
              uint8_t* base) {
  const uint32_t every = REXCVAR_GET(pinyon_shift_reference_verify);
  if (!every) {
    original(ctx, base);
    return;
  }
  const uint64_t call = entry.calls.fetch_add(1, std::memory_order_relaxed);
  if (call % every != 0) {
    original(ctx, base);
    return;
  }

  const PPCContext input = ctx;
  PPCContext reference_ctx = input;
  rex::ppc::RefLogBegin();
  reference(reference_ctx, base);
  rex::ppc::RefRollback();
  original(ctx, base);

  std::string difference = CompareReferenceRegisters(reference_ctx, ctx);
  if (difference.empty()) {
    if (const auto* write = rex::ppc::RefFirstDifference()) {
      difference = fmt::format("memory {:08X}+{}", write->guest, unsigned(write->size));
    }
  }
  entry.verified.fetch_add(1, std::memory_order_relaxed);
  if (difference.empty())
    return;
  const uint64_t count = entry.mismatched.fetch_add(1, std::memory_order_relaxed);
  if (count >= kMaxLoggedMismatches)
    return;
  diagnostics::RecordEvent("reference.mismatch",
                           {{"name", entry.name},
                            {"difference", difference},
                            {"r3", Hex64(input.r3.u64)},
                            {"r4", Hex64(input.r4.u64)},
                            {"r5", Hex64(input.r5.u64)},
                            {"r6", Hex64(input.r6.u64)},
                            {"f1", Hex64(input.f1.u64)},
                            {"f2", Hex64(input.f2.u64)},
                            {"lr", fmt::format("{:08X}", static_cast<uint32_t>(input.lr))}});
}

}  // namespace

void RecordSummary() {
  std::lock_guard lock(registry_mutex);
  uint64_t calls = 0, verified = 0, mismatched = 0, functions_mismatched = 0;
  for (const Entry* entry : registry) {
    calls += entry->calls.load(std::memory_order_relaxed);
    verified += entry->verified.load(std::memory_order_relaxed);
    const uint64_t m = entry->mismatched.load(std::memory_order_relaxed);
    mismatched += m;
    functions_mismatched += m ? 1 : 0;
  }
  diagnostics::RecordEvent("reference.summary",
                           {{"functions", std::to_string(registry.size())},
                            {"calls", std::to_string(calls)},
                            {"verified", std::to_string(verified)},
                            {"mismatched", std::to_string(mismatched)},
                            {"functions_mismatched", std::to_string(functions_mismatched)}});
}

}  // namespace pinyon_shift::guest_native::reference

// One strong `sub_X` per reference function, routing through Dispatch.
#define REX_REFERENCE_FUNCTION(address, name)                                                  \
  extern "C" REX_FUNC(__imp__##name);                                                          \
  extern "C" REX_FUNC(ref_##name);                                                             \
  namespace {                                                                                  \
  ::pinyon_shift::guest_native::reference::Entry entry_##name{#name, address};                 \
  ::pinyon_shift::guest_native::reference::Registration registration_##name{entry_##name};     \
  }                                                                                            \
  extern "C" REX_FUNC(name) {                                                                  \
    ::pinyon_shift::guest_native::reference::Dispatch(entry_##name, &__imp__##name, &ref_##name, \
                                                      ctx, base);                              \
  }

#include "pinyon_shift_reference.h"  // generated beside the recompiled code
