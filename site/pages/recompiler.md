---
title: Recompiler
section: Internals
order: 2
description: How ShiftGlue turns Forza Horizon's default.xex into C++, finds every function, and matches the Xenon CPU's floating-point and vector behaviour.
---

# Recompiler

[ShiftGlue](https://github.com/arcanite24/shiftglue-sdk) is a fork of ReXGlue 0.10.0. Its generator, `rexglue`, reads the game's executables and writes one C++ function per guest function. Setup runs it on the player's machine, so no translated code is ever distributed.

## Inputs

`config/rexglue/pinyon_shift_manifest.toml` names three images: `default.xex` and the two facade modules `SpeechFacade_default.xex` and `XMediaFacade_default.xex`, included because traces showed the game loading them and calling into them. Each image has an analysis file in `config/rexglue/analysis/`. Only one retail executable is accepted, identified by its SHA-256.

The generator boots the runtime in a tool mode and loads each XEX through the same loader the game uses (derived from Xenia's): it decrypts the session key and the image with AES, decompresses the basic and LZX formats, and can apply `.xexp` title update deltas.

## Finding the functions

A static recompiler has to know where every function starts and ends before it writes a line of output. ShiftGlue's analysis runs in phases, and the build fails rather than guess.

{{diagram:recompiler-phases|The analysis phases. Configuration supplies what the binary doesn't make discoverable.}}

| Phase | What it finds |
| --- | --- |
| Register | Imports; the compiler's register save and restore helpers, found by byte signature; every `.pdata` entry; MSVC exception tables (unwind maps, try blocks, IP-to-state maps); functions declared in configuration |
| Scan | Code and data regions in each section |
| Discover | Walks each function: `bl` targets become functions, plain `b` targets don't; jump tables; MSVC RTTI vtables, through Complete Object Locators and the slots after them |
| Gap fill | Code nothing reached is split at `blr` and tail calls; fragments a stronger source already covers are dropped |
| Merge | Resolves jumps and seals function bounds |
| Validate | Any call that lands on no function is an error |

A scan for `lis`/`addi` function-pointer pairs exists but is off: it found too many false positives.

**Jump tables.** Four MSVC patterns are recognized: absolute 32-bit entries (`lwzx`), and byte, shifted-byte and halfword offsets from a base (`lbzx`, `lhzx`). The table size comes from the `cmplwi` bounds check found by scanning backwards, at most 64 instructions and 512 entries. When the pattern is broken, the table is declared by hand: in the title update an `lfd` between the bound check and the branch made the scan read too far and merge the next function, which one `[[switch_tables]]` entry fixed.

**Declared boundaries.** The base analysis declares 113 function sizes. Most are adjustor and tail thunks and vtable targets that have no `.pdata` entry, or regions that gap fill had merged into one function. Each carries a comment with its evidence, such as a vtable target proven at run time. Discovery that disagrees with a declared size is a warning; any new codegen warning fails the build, and `config/rexglue/accepted-codegen-warnings.json` accepts exactly three known ones.

## What the generator emits

Every guest function becomes:

```cpp
void sub_82XXXXXX(PPCContext& __restrict ctx, uint8_t* base);
```

`ctx` holds the guest registers: r0–r31, f0–f31, the 128 VMX128 vector registers, `lr`, `ctr`, `xer` (as separate so/ov/ca bytes), each `cr` field as four bytes (lt, gt, eq, so), `fpscr`, the reservation and a dispatch address. `base` is the host address of guest address 0.

| Guest construct | Generated code |
| --- | --- |
| `bl` to a known function | a direct C++ call |
| `b` into another function | `[[clang::musttail]]` call, so loops that cross functions don't grow the host stack |
| `bctrl`, `bctr` through a pointer | lookup in a dispatch table of host pointers, one slot per guest instruction, placed after the image in guest memory; misses fall back to a search of all loaded modules |
| Jump table | a C++ `switch` on a 32-bit index |
| Return address inside the caller | an entry `switch` on `ctx.dispatch_address`, so the runtime can resume a function in the middle |
| `lwarx` / `stwcx.` | `std::atomic` compare-exchange on a same-width copy of the reservation |
| `mtmsrd` (interrupts off) | enter the runtime's global critical region |
| `sync`, `lwsync`, `eieio`, `isync` | nothing on x86-64; seq_cst, acq_rel, seq_cst and acquire fences on AArch64 |
| `mftb` | the runtime's guest tick count |
| Guest `setjmp` / `longjmp` | a host `jmp_buf` per guest buffer, held in a thread-local map |

The resume switch exists because guest threads can be re-entered: when the game calls `KeSetCurrentStackPointers`, the runtime `longjmp`s to the thread's base and dispatches again at `ctx.lr`. In the base image 56,860 functions start with that switch.

**Condition registers in locals.** Generated code keeps guest registers in `ctx`, so every compare stores its CR bits to memory that a guest store might alias, and Clang can't drop or forward them. With `cr_as_local`, a function keeps the CR fields it uses in C++ locals, loaded from `ctx` on entry. Writing them all back and reloading them around every call cost what it saved: binaries grew 13–26 % for no change in instructions. What made it pay is the PowerPC calling convention:

- cr2–cr4 are preserved across calls, and the other fields are dead at a call and at a return.
- So a call, return or tail call writes back only the cr2–cr4 locals and reloads nothing.
- Hooks that read `ctx`, the `setjmp` copy, `longjmp` and exceptions keep a full write-back and reload.
- A function resumed mid-body loads its locals from `ctx` on entry, which is correct because only preserved fields are live at a return address.

On the Odin this cut guest instructions per second by 11 % on the render thread and 12 % on the simulation thread, and the executable shrank 9 %. The other registers stay in `ctx`.

Each function is defined as a weak alias, so host code can replace a guest function by defining the same symbol (Mach-O has no overridable alias; on macOS it is a weak thunk instead). The price is that Clang can't inline guest calls, even with LTO.

## Memory access

Guest memory stays big-endian. Every load and store is a `volatile` access through `__builtin_bswap16/32/64` at `base + address`. Until October 2026 an address at or above `0xE0000000` also added `0x1000`, because Windows mapped that view 4 KB short of its place in the physical heap ([why](runtime.md#guest-memory)); the select behind that add was a compare, a conditional set and a shift on 70 % of all guest accesses. Skipping it for accesses through `r1`, the stack pointer, had already made the binaries 5.4–5.7 % smaller and cut the Odin's guest instructions per second by 17–18 % on the simulation and render threads. Mapping the view exactly removed the remaining 625,000 selects: with the count register and XER kept in locals (below), the generated x86-64 code went from 17.7 M to 13.7 M host instructions (−22.6 %) and from 75.0 to 59.7 MB of code (−20.4 %). Only Apple silicon, with 16 KB pages, still adds the offset. Addresses in `0x7F000000`–`0x7FFFFFFF` go to the MMIO handler.

**Count register and XER in locals.** Both are volatile in the PowerPC ABI and dead at every return address, so a function keeps them in zero-initialized locals that never touch `ctx` (`ctr_as_local`, `xer_as_local`). FH1 has no overflow-enabled integer instruction and its one `mtxer` is a context restore, so XER's summary-overflow bit is never set and the copy of it into every compare's condition field folds to zero.

## Floating point and vectors

Generated code runs FPU instructions with denormals and VMX instructions with flush-to-zero, as the Xenon does. It switches the host's MXCSR (FPCR on ARM) only when the mode changes. The tracked mode used to be forgotten at every label, so the first float instruction after a label tested the register and often rewrote it. A pass over each generated function now computes the mode at every label from all the paths into it, and drops a toggle where every path has already set that mode. That removed 29 % of the conditional toggles and 6 % of the Odin audio thread's instructions. Calls still reset the tracked mode, because the callee may leave either. The guest rounding mode maps to host rounding, and `mtfsf` honours its field mask.

| Behaviour | How it's matched |
| --- | --- |
| `fmadd` family | `std::fma`, single-precision forms rounded through `float`; one instruction with the FMA3 build, bit-identical either way |
| `vmsum3fp128`, `vmsum4fp128` | products summed in double in the console's order; a finite dot product that overflows single precision returns the canonical QNaN, as the hardware does, where SSE's `dp_ps` gives infinity. The game's collision code compares those results. |
| Saturating packs and adds | `vpkuhus`, `vpkd3d128` (16-bit normalized packs clamp to ±32767), `vaddsws` (overflow detection), `vctuxs` (NaN to 0) |
| `fctid`, `fctidz`, `fctiwz` | NaN inputs give the console's results |
| Floating-point compares | set the `un` bit for NaN |
| `stvlx`, `stvrx` partial stores | tested at offsets 0, 1, 4, 8, 12 and 15, aliasing cases and 512 seeded random cases |
| VMX128 decoding | decoded ahead of the ppc405 opcodes it overlaps |

Vector code is lowered through SIMDe, which maps the SSE intrinsics to NEON on ARM. 1,480 PPC instruction tests with 6,549 assertions pass.

## Building the output

Output is split into files of at most 1 MiB, with the function-to-file assignment kept stable between runs (`codegen.partition.json`) so a regeneration doesn't rebuild everything. CMake runs the generator with a depfile covering the manifest, the analysis files, the three images and the SDK version, then builds the main image as an object library with a precompiled header and the facades as shared libraries.

| Setting | Value |
| --- | --- |
| Compiler | Clang 20.1.8, pinned and SHA-256 checked (Command Line Tools clang on macOS, NDK r29 on Android) |
| Optimization | `-O3`, `-ffp-contract=off`, `-fno-strict-aliasing` (measured to change nothing in the output), `-gline-tables-only`. `-ffp-model=strict` is an option: it costs 1–2 % host instructions for a risk never observed. No asynchronous exceptions: no generated unit has an SEH scope |
| x86-64 baseline | SSE4.1; an FMA3 variant when the CPU has it, guarded at start. An x86-64-v3 variant (`-CpuBaseline v3`) is opt-in: MOVBE replaced a fifth of the byte swaps in the audio routines, under 1 % of their instructions |
| Linux x86-64 | `-mcmodel=large -Wl,--no-relax` for the 300 MB of code |
| Android | `-Wl,-Bsymbolic-functions`: PLT stubs fell from 1.6 % to 0.1 % of cycles |
| LTO, PGO | wired up, off. ThinLTO is neutral on guest-thread instructions. PGO trained on one route and measured on another cuts 1–6 % per guest thread on the Odin, but a release would need a profile kept in step with the generated code |
| First build | 20 to 60 minutes and about 25 GB on a PC; about 20 minutes on an M4 Pro; about 35 on the Deck |

## The title update build

Title update v4 is a second executable. The v4 patches were made for a later disc revision, but applied to the USA disc they reproduce the v4 images exactly: every page verifies against v4's own SHA-1 page chain. The v4 build has its own manifest, analysis and generated tree, and a translated address map:

1. `tools/map-fh1-v4-addresses.py` matches functions by their normalized bodies (branch and absolute immediates masked, unique in both images), then by call-graph anchoring, then by unique context windows, then `lis`/`addi` data pairs. 27,556 of 57,127 functions match by body alone. Unmapped addresses are reported, never guessed.
2. `tools/port-fh1-v4-analysis.py` rewrites the analysis: all hooks, declared functions, `setjmp`/`longjmp` and CRT routes mapped, with four hand overrides. A rule declaring virtual-call thunks outside `.pdata` found 253 in v4, and recovers 66 of the base image's 70 hand-listed thunks.
3. Host code writes guest addresses as `FH1_ADDR(base address)`, translated at compile time from a verified table; an unmapped address fails the compile. Structure offsets that moved are listed in `config/mod/fh1-offsets-v4.toml`, each with a matching site in both images.

Details: [TITLE_UPDATE_V4_BACKLOG.md](https://github.com/arcanite24/pinyon-shift/blob/dev/docs/TITLE_UPDATE_V4_BACKLOG.md).
