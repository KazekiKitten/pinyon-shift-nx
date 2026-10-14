// NN-0.8 calibration bench: the generated code's support macros, with one
// switch per translation overhead (docs/NEAR_NATIVE_RESEARCH.md NN-0.8).
//
// This is the pch the generator emits (rexglue pch_h.inja), cut down to what a
// single guest function needs, so a generated function body copied into the
// bench (never committed: docs/LEGAL.md) compiles as it does in the game. Each
// overhead can be turned off on its own:
//
//   NN08_NOVOL    guest loads and stores (heap and stack) are not volatile
//   NN08_NOSWAP   scalar guest loads and stores do not byte swap; vector
//                 loads keep their lane-reversing shuffle (removing it would
//                 change lane semantics), so data read both ways is wrong
//   NN08_NOFLUSH  no MXCSR/FPCR writes for the guest's flush-to-zero mode
//   NN08_INLINE   helpers (save/restore, callees) in the caller's unit, no
//                 musttail, so the compiler may inline them
//   NN08_NOLR     link-register stores (ctx.lr = ...) dropped (prepare.py)
//   NN08_LOCALS   guest registers in host locals inside a function, written
//                 back to ctx only at calls and returns (prepare.py)
#pragma once

#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <climits>
#include <cmath>

#include <rex/ppc/context.h>
#include <rex/ppc/intrinsics.h>

using rex::ppc::VectorMaskL;
using rex::ppc::VectorMaskR;
using rex::ppc::VectorShiftTableL;
using rex::ppc::VectorShiftTableR;

using u8 = uint8_t;
using u16 = uint16_t;
using u32 = uint32_t;
using u64 = uint64_t;

// Function definitions: plain C++ functions inside the variant's namespace.
#ifdef NN08_INLINE
#define NN08_FN_ATTR static inline
#else
#define NN08_FN_ATTR __attribute__((noinline))
#endif
#define REX_FUNC_DECL(name) void name(PPCContext& __restrict ctx, uint8_t* base)
#define DEFINE_REX_FUNC(name) NN08_FN_ATTR REX_FUNC_DECL(name)

#if defined(__clang__) && !defined(NN08_INLINE)
#define REX_TAIL_CALL(name) [[clang::musttail]] return name(ctx, base)
#else
#define REX_TAIL_CALL(name) \
  do {                      \
    name(ctx, base);        \
    return;                 \
  } while (false)
#endif

#define REX_FUNC_PROLOGUE() __builtin_assume(((size_t)base & 0x1F) == 0)

// The physical-view offset: 0 on Windows and on 4 KB-page Linux/Android
// builds (REX_PHYSICAL_HEAP_4K_PAGES, the shipped default).
#define REX_PHYS_HOST_OFFSET(addr) 0u
#define REX_RAW_ADDR(x) (base + (u32)(x) + REX_PHYS_HOST_OFFSET(x))

#ifdef NN08_NOVOL
#define NN08_QUAL
#else
#define NN08_QUAL volatile
#endif

#ifdef NN08_NOSWAP
#define NN08_BS16(v) ((u16)(v))
#define NN08_BS32(v) ((u32)(v))
#define NN08_BS64(v) ((u64)(v))
#else
#define NN08_BS16(v) __builtin_bswap16(v)
#define NN08_BS32(v) __builtin_bswap32(v)
#define NN08_BS64(v) __builtin_bswap64(v)
#endif

#ifdef NN08_NOVOL
// Plain accesses through memcpy so the compiler is free to combine them; the
// guest memory may be unaligned.
template <typename T>
static inline T nn08_ld(const uint8_t* p) {
  T v;
  std::memcpy(&v, p, sizeof(T));
  return v;
}
template <typename T>
static inline void nn08_st(uint8_t* p, T v) {
  std::memcpy(p, &v, sizeof(T));
}
#define NN08_LD(T, p) nn08_ld<T>(p)
#define NN08_ST(T, p, v) nn08_st<T>((p), (T)(v))
#else
#define NN08_LD(T, p) (*(volatile T*)(p))
#define NN08_ST(T, p, v) (*(volatile T*)(p) = (T)(v))
#endif

#define REX_LOAD_U8(x) NN08_LD(u8, base + (u32)(x))
#define REX_LOAD_U16(x) NN08_BS16(NN08_LD(u16, base + (u32)(x)))
#define REX_LOAD_U32(x) NN08_BS32(NN08_LD(u32, base + (u32)(x)))
#define REX_LOAD_U64(x) NN08_BS64(NN08_LD(u64, base + (u32)(x)))
#define REX_STORE_U8(x, y) NN08_ST(u8, base + (u32)(x), (y))
#define REX_STORE_U16(x, y) NN08_ST(u16, base + (u32)(x), NN08_BS16((u16)(y)))
#define REX_STORE_U32(x, y) NN08_ST(u32, base + (u32)(x), NN08_BS32((u32)(y)))
#define REX_STORE_U64(x, y) NN08_ST(u64, base + (u32)(x), NN08_BS64((u64)(y)))

#define REX_STACK_LOAD_U8(x) REX_LOAD_U8(x)
#define REX_STACK_LOAD_U16(x) REX_LOAD_U16(x)
#define REX_STACK_LOAD_U32(x) REX_LOAD_U32(x)
#define REX_STACK_LOAD_U64(x) REX_LOAD_U64(x)
#define REX_STACK_STORE_U8(x, y) REX_STORE_U8(x, y)
#define REX_STACK_STORE_U16(x, y) REX_STORE_U16(x, y)
#define REX_STACK_STORE_U32(x, y) REX_STORE_U32(x, y)
#define REX_STACK_STORE_U64(x, y) REX_STORE_U64(x, y)

#define REX_MM_LOAD_U8(x) REX_LOAD_U8(x)
#define REX_MM_LOAD_U16(x) REX_LOAD_U16(x)
#define REX_MM_LOAD_U32(x) REX_LOAD_U32(x)
#define REX_MM_LOAD_U64(x) REX_LOAD_U64(x)
#define REX_MM_STORE_U8(x, y) REX_STORE_U8(x, y)
#define REX_MM_STORE_U16(x, y) REX_STORE_U16(x, y)
#define REX_MM_STORE_U32(x, y) REX_STORE_U32(x, y)
#define REX_MM_STORE_U64(x, y) REX_STORE_U64(x, y)

#if defined(__aarch64__)
#define REX_PPC_SYNC() __atomic_thread_fence(__ATOMIC_SEQ_CST)
#define REX_PPC_LWSYNC() __atomic_thread_fence(__ATOMIC_ACQ_REL)
#define REX_PPC_EIEIO() __atomic_thread_fence(__ATOMIC_SEQ_CST)
#define REX_PPC_ISYNC() __atomic_thread_fence(__ATOMIC_ACQUIRE)
#else
#define REX_PPC_SYNC() ((void)0)
#define REX_PPC_LWSYNC() ((void)0)
#define REX_PPC_EIEIO() ((void)0)
#define REX_PPC_ISYNC() ((void)0)
#endif

// The bench never takes an indirect call; reaching one is a setup error.
#define REX_CALL_INDIRECT_FUNC(x) std::abort()
#define REX_CALL_FUNC(x) x(ctx, base)
#define REX_UNIMPLEMENTED(addr, opcode) std::abort()

// Flush-mode writes. prepare.py rewrites ctx.fpscr.<op>() into NN08_FPSCR(<op>).
#ifdef NN08_NOFLUSH
#define NN08_FPSCR(op) ((void)0)
#define REX_SET_FLUSH_MODE(enable) ((void)0)
#else
#define NN08_FPSCR(op) ctx.fpscr.op()
#define REX_SET_FLUSH_MODE(enable) \
  do { if (enable) ctx.fpscr.enableFlushMode(); else ctx.fpscr.disableFlushMode(); } while (0)
#endif
