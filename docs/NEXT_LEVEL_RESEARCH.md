# Next-level research: code generation, reverse engineering and runtime

Researched 2026-10-12 at `dev` `d4ba71a` (ShiftGlue `c5a124c`). This page
answers three questions:

1. Which big projects would take Pinyon Shift furthest from here?
2. Can more reverse engineering make the recompiled code more specialized
   and much faster?
3. How would we build a XenonRecomp/XenosRecomp-style toolchain without
   ReXGlue's costs, and lower resource use?

It extends [RECOMP_OPTIMIZATION_SURVEY.md](RECOMP_OPTIMIZATION_SURVEY.md)
(#456) and the [performance backlog](PERFORMANCE_BACKLOG.md) without
repeating them. Nothing was built or run for this page. The numbers come
from four places:

- counts over the generated tree (`.local/generated/default`) and the
  Release objects (`out/build/win-amd64-release`);
- the repository's recorded benchmarks and perf CSVs;
- the SDK source;
- primary sources for other projects.

Every estimate is marked as one. The full research notes are kept locally
in `.local/backlog-research/next-level-2026-10-12/`, which is not
committed.

Licences limit what we take:

- XenonRecomp, XenosRecomp and plume (MIT), and Xenia, Canary and Edge
  (BSD-3): code with attribution.
- UnleashedRecomp and Rayman Origins Recomp (GPL-3): ideas only.
- Projects without a licence: ideas only.
- TiP-Recomp: its author does not consent to AI use of the work, so it
  was not analysed.

## Summary

- **Don't start over with a hedge-dev-style stack. Rebuild ShiftGlue's
  code generator around XenonRecomp's one good idea.**
  - **That idea:** every function has a single entry, so guest
    registers can live in host registers.
  - **What blocks it here:** ShiftGlue gave 56,860 of FH1's 76,499
    functions a resume `switch` (342,683 interior entry points). That
    switch is our addition, not upstream ReXGlue's. It exists only
    because the runtime abandons the host call chain when a guest fiber
    switches stacks (`KeSetCurrentStackPointers` calls `XThread::Reenter`
    only when the thread has a guest fiber).
  - **The way out is already half built:** the SDK has host-fiber
    versions of the XAPI fiber functions, but FH1 maps none of them.
  - **Why not a hand-written runtime:** FH1 needs exactly what
    UnleashedRecomp's lean runtime lacks (fibers, MSVC exceptions, two
    DLL modules, XMA, STFS DLC, the v4 title update). Our GPU path is
    already native.
- **About 43-46 % of the host instructions in the generated code are
  bookkeeping, not the game's work:**
  - 24 % plain moves to and from the `ctx` register file;
  - about 14 % the `0xE0000000` physical-view select;
  - 4.7 % byte swaps.

  This is a static count over a sample of 12,021 functions. The two
  hottest audio routines are 54-57 % bookkeeping.
- **The cheapest large win is the physical-view select.**
  - **Why it exists:** on Windows, desktop builds map guest views with
    `MapViewOfFileEx`, which needs 64 KB alignment, so the `0xE0000000`
    view can't start at its 4 KB offset and every access adds `0x1000`
    back.
  - **The fix:** placeholder views (`MapViewOfFile3`, Windows 10 1803+)
    accept 4 KB offsets, and the SDK already calls them in its
    non-desktop branch. On 4 KB-page Linux and Android kernels the offset
    is always 0.
  - **Evidence:** removing the select only for r1-based accesses already
    cut Odin guest instructions 17-18 % (#431).
- **The two largest wins sit in different places:**
  - **Low-end devices:** register locals behind single-entry functions,
    plus the select removal, are the largest lever on guest CPU time.
    That matters on the Odin, the Deck, low-spec PCs, and for heat and
    battery.
  - **Desktop 1x:** the limit is not guest code. Three host threads
    re-read and re-derive command lists that are 96 % identical every
    frame: about 18 ms of CPU per 8.4 ms frame, about 2.2 cores.
    Compiling the title's display lists once (DR-5.3, then DR-3.1, DR-4.1
    and DR-4.2) is the lever there. XenosRecomp's register-file, bindless
    shader interface is the piece of it worth taking.
- **For speed, the useful reverse engineering is not function names.**
  It is four kinds of fact the generator can apply everywhere:
  - register signatures and ABI conformance;
  - memory classes (private, shared, polled, GPU-visible);
  - indirect-call targets;
  - which code can be on a stack at a fiber switch.

  Get them from an "RE build" of the game itself, with probes in the
  generator's macros, and from a local Ghidra workspace. Feed them to the
  generator through a versioned knowledge base. Dynamic data may choose
  what to specialize; only static proof or an exact guard may permit it.

## Where the cost is today

### Generated code (static, `win-amd64-release`)

| Measure | Value |
| --- | --- |
| Functions, guest instructions | 76,499; 3,651,030 |
| Partition source | 261 MiB, of which 24.5 % is per-instruction comments |
| Host `.text` | 75 MB, about 20 host bytes per 4-byte guest instruction |
| `ctx` memory operands | 26.8 % of host instructions (24.4 % plain moves; 60 % of them stores) |
| Physical-view select | about 13.9 % of host instructions, on 70.3 % of guest accesses (725,461 sites) |
| `bswap` | 4.7 % of host instructions (964,062 swaps in source) |
| Resume switches | 56,860 functions, 342,683 cases; `dispatch_address` cleared on entry in all 76,499 |
| Calls | 296,172 direct, 48,100 indirect, 31,828 tail calls; 342,942 `ctx.lr` stores; 49,841 save/restore helper calls |
| Flush-mode toggles left | 38,248 |
| Weak aliases | 76,499: no guest function can be inlined |
| Dispatch tables | about 35 MiB committed and zeroed (main table 11.3 % used); `PPCFuncMappings` 6.7 MB of writable `.data` |
| Recomp compile | 28-52 CPU-minutes; the critical path is one 27,503-instruction function (`sub_8241A370`, 54-112 s) |

An ABI liveness model over 12,018 of the sampled functions shows what
register locals could remove. The model keeps today's semantics except
for calls, which follow the PowerPC convention.

| Model | `ctx` traffic vs today | Host instructions saved |
| --- | --- | --- |
| Perfect forwarding, today's call semantics | -21 % | 5.4 % |
| ABI at calls, resume switch kept | -33 % | 8.2 % |
| ABI at calls, no resume switch | -47 % | 11.8 % |
| No resume switch, and no `ctx.lr` store where re-entry is impossible | -55 % | 13.9 % |

Only 1.2 % of register writes are dead. The waste is writing every
result to memory and reading it back. The resume switch is what blocks
the load side: removing it halves the reloads after calls, from 177 k to
82 k.

These are static shares. They don't weigh instructions by how often they
run. Dynamic counters (top-down analysis on the Deck, `simpleperf` on the
Odin) are item NL-0.3.

### Host threads (1x race, 120 fps limit, RTX 4080)

Frames with at least 5,000 draws, from the 2026-10-07 low-spec CSV:

| Thread | CPU a frame |
| --- | --- |
| GPU Commands (PM4 decoder) | 8.38 ms, including up to 2 ms of `WAIT_REG_MEM` yield-spinning |
| GPU Recorder | 6.82 ms, about 1.3 µs a draw |
| GPU Submission | 2.97 ms |
| Title render thread | 2.36 ms, plus a 3.72 ms fence wait |
| Audio | about 28-29 % of a core |

The frame median is 8.43 ms.

### Memory

| Item | Size |
| --- | --- |
| Process resident | 2.0-2.1 GB at every scale, so render targets don't drive it; no breakdown by region exists |
| VRAM | 0.9-1.13 GB at 1x, 3.3 GB at 2x with MSAA, 4.3 GB at 3x |
| Executor surfaces | 265 MB at 1x, 2.0-2.4 GB at 2x/3x; sized to the EDRAM period and never freed |
| Physical heap | 512 MB committed at start, mapped three times |
| GPU shared-memory mirror | 512 MB; real RAM on Turnip, which can't make it sparse |
| Textures | stored twice: the tiled guest copy and the untiled host copy (146-602 MB) |

## The ReXGlue inheritances, and what replaces each

| Inheritance | Why it exists | Cost here | Replacement | Item |
| --- | --- | --- | --- | --- |
| Registers written through to `ctx` | interior re-entry, hooks and imports read `ctx` | 26.8 % of host instructions | locals synced by the PowerPC ABI, as #467 did for CR | NL-1.4 |
| Interior resume switch (ShiftGlue's addition) | guest fibers abandon the host call chain | irreducible loops; doubled reloads; 342,683 table entries | guest fibers on host fibers, so functions are single-entry | NL-1.2 |
| Physical-view select | 64 KB view alignment on Windows; 16 KB-page kernels elsewhere | about 14 % of host instructions | exact 4 KB mapping; compile-time 0 on 4 KB kernels | NL-1.1 |
| Weak alias + `noinline` on every function | host code overrides by defining the symbol | no inlining, even with LTO; 7.5 MB of dynamic symbol tables on Android | strong symbols except a declared override list | NL-1.5 |
| `volatile` + `bswap` on every access | MMIO, cross-thread flags, one exact model | blocks forwarding; 4.7 % `bswap` | plain stack accesses, then stack slots as locals; MOVBE | NL-1.6, NL-1.8 |
| One host pointer per guest instruction | O(1) lookup of every resume address | 35 MiB committed, 11 % used | entries for function starts only, 4-byte entries, const mappings | NL-1.9 |
| PM4 decode and per-draw derivation every frame | Xenia's general GPU model | about 2.2 cores at 1x | compile display lists once, with a register-file, bindless ABI | NL-3 |
| XMA as MMIO hardware | Xenia models the audio chip | the trap is about 7 points of the audio thread | call the decoder at the guest XMA API | NL-4.1 |
| Kernel objects behind the global lock and a handle table | Xenia's object model | #416 stalls on Android | atomics in guest dispatcher headers with `WaitOnAddress`/futex | NL-4.3 |
| Physical heap committed up front; surfaces never freed | inherited | 512 MB commit; 2 GB of VRAM at 2x/3x | commit on demand; surfaces sized by role and evicted | NL-4.4, NL-3.5 |

## What to take from XenonRecomp and XenosRecomp

**Lineage.** ReXGlue is not a git fork of XenonRecomp. It is a rewrite
that keeps:

- XenonRecomp's disassembler tables and configuration schema;
- `PPCContext`, the first VMX helpers and the flush-mode emitter;
- the jump-table classes and the function-table formula.

It wraps them in a phased analysis and Xenia's runtime. ShiftGlue's
analysis is ahead of XenonRecomp in several ways:

- MSVC exception tables, RTTI vtables and DLL modules;
- guaranteed tail calls and AArch64 fences;
- exact FP corner cases, which FH1's collision code depends on.

| Take | Why |
| --- | --- |
| Single-entry functions and all register-local options (XenonRecomp, MIT) | XenonRecomp's README credits removing the save/restore helpers as its largest single gain, and reports about 20 MB smaller code and "several ms" faster frames, with no method. Our CR-only version measured -11/-12 %. |
| Mid-asm hooks that pass registers by reference (XenonRecomp) | Lets hooks coexist with register locals without a full sync |
| A register-file, bindless shader interface with one specialization mask (XenosRecomp, MIT) | The runtime half of XenosRecomp. It removes the per-draw constant gather, about 1,130 of 5,800 recorder cycles a draw, but only pays together with compiled display lists (NL-3) |
| One embedded, compressed, hash-indexed shader blob built at install | Vulkan translates every shader again at each start, and setup plays a 125 s route to warm caches. An offline pack from the 3,349-program disc corpus shortens setup and start. Driver pipeline compiles remain. |
| Pipelines built when the work is created (UnleashedRecomp idea, GPL) | FH1's analogue of asset loads is display-list creation: build pipelines then, not on first draw |

| Don't take | Why |
| --- | --- |
| UnleashedRecomp's hand-written kernel, o1heap, flat 4 GiB | FH1 needs fibers, exceptions, DLL modules, XMA, STFS DLC and the title update; the guest allocator is 0.05 % of a race (#468) |
| D3D-call hooking over plume | Only 42 of about 5,000 draws a frame go through the title's emitter; the rest are prebuilt lists |
| XenosRecomp itself | It ignores `CondExec` conditions, vertex-fetch formats, LOD and bias, and 1D textures, all of which FH1 uses; it failed to compile FH1's shaders (PB-10) |
| XenonRecomp's FP shortcuts | No FMA, `dp_ps` dot products: FH1 compares `vmsum` results |
| `skip_msr` | Guest code masks interrupts to guard per-CPU data |
| A direct LLVM-IR backend, for now | Everything ranked here can be expressed in C++ under Clang 20. Revisit only if `-ftime-trace` shows the front end dominating the build (NL-0.3) |

## Proposed projects

Effort: S is days, M a week or two, L longer. Every codegen item keeps
the project's gates:

- the save hash, `expect-simulation-time`, route images and frame
  replays from pinned seeds;
- Odin per-thread guest instructions at the 30 fps limit, four or more
  runs per build;
- cycles, not only instructions, for front-end work: `perf stat` on the
  Deck, `simpleperf` on the Odin.

Each item that is kept or rejected goes on the docs site in the same
change.

### NL-0 Safety net and baseline (do first)

| ID | Work | Why | Effort |
| --- | --- | --- | --- |
| NL-0.1 | **ABI poison build.** After every call returns, overwrite the dead volatile `ctx` fields with poison and assert that the non-volatile fields are unchanged. Run the route corpus. | Proves the calling convention on FH1 before NL-1.4 relies on it. It runs with today's codegen and names any function that breaks the ABI. No published translator does this check. | S |
| NL-0.2 | **Lockstep codegen verify.** Generalize `guest_native` verify: build the reference codegen of sampled functions into the same binary, run both on cloned state every Nth call, and compare live registers and written memory. | The gate for NL-1.1, NL-1.4 and NL-1.6 | S-M |
| NL-0.3 | **Missing measurements:** resident memory and commit by region (VMMap, `/proc/<pid>/smaps`); time to the first guest instruction, including table zeroing and 419 k registrations; `-ftime-trace` on a few partitions; dynamic instruction mix and front-end stalls (top-down analysis on the Deck, `simpleperf` i-cache and iTLB on the Odin) | Ranks NL-1.8, NL-1.9 and NL-4.4, and settles the C++-vs-IR question | S |
| NL-0.4 | **Import the Canary/Edge PPC test corpus** (571-581 tests against our 167) and triage it. Known gaps: `vcmpbfp` with a NaN (Edge `e4b13738c3`), `vmaxfp`/`vminfp` with a QNaN, and `vmaddfp`, which rounds twice. | Codegen semantics coverage before large codegen changes | S-M |
| NL-0.5 | **Decide the generated-unit flags.** The SDK's `-ffp-model=strict` and `-fno-strict-aliasing` apply only to its own sources, not to Pinyon's recomp units. Without strict FP, LLVM may move FP operations across MXCSR writes. `-fasync-exceptions` is on although no SEH scope is emitted. | Correctness first. Measure each flag's cost. | S |

### NL-1 Code generation v2 in ShiftGlue

The expected gains for this track are estimates, except where marked as
measured.

| ID | Work | Evidence and expected value | Effort | Risk |
| --- | --- | --- | --- | --- |
| NL-1.1 | **Remove the physical-view select.**<br>• Windows: reserve with `VirtualAlloc2(MEM_RESERVE_PLACEHOLDER)`, map each view with `MapViewOfFile3(MEM_REPLACE_PLACEHOLDER)` at its exact 4 KB offset, and make `REX_PHYS_HOST_OFFSET` `0u`.<br>• Linux and Android: a build option that emits `0u` and refuses to start on a kernel with pages above 4 KB. The APK and the Deck build are made per device, so the option can follow the target.<br>• macOS arm64 (16 KB pages): keep the offset, but as an unlikely branch, which costs two instructions on x86-64 against four or five today; check the AArch64 output, where Clang may turn it back into a select.<br>• Check the write-watch and protection arithmetic, which uses `host_address_offset`, and the GPU's physical views. | The select is about 14 % of host instructions and 17 % in the hottest functions. Removing it for r1 accesses alone measured -17/-18 % Odin guest instructions. Estimate: -10 to -25 % on Windows and 4 KB Android. | S-M | Low-medium |
| NL-1.2 | **Guest fibers on host fibers, then single-entry functions.**<br>• Map FH1's XAPI fiber functions to the SDK's existing `[rexcrt]` fiber group (`src/kernel/crt/threading.cpp`). The only two callers of `KeSetCurrentStackPointers` are `sub_830ED900` and `sub_830ED910`, the fiber switch (recorded on the site's Executable page, `site/findings/executable.toml`).<br>• Confirm with the `stack.reentry` trace that `Reenter` no longer fires on the route matrix.<br>• Find any other interior entries: host `Execute` at a registered interior address, exception continuations.<br>• Emit resume labels only for that proven set, possibly none. | Removes 56,860 switches, 342,683 cases, 76,499 dispatch clears and most table registrations. Loops become reducible, so LICM, unrolling and vectorization see them. It makes `skip_lr` legal outside the remaining set. Enabler for NL-1.4: halves the post-call reloads in the model. | M-L | Medium-high |
| NL-1.3 | **CTR and XER as locals.** Both are dead across calls. `xer.so` is never set (0 overflow-form instructions, one `mtxer`, a context restore), so the SO copy in 192,632 compares folds to 0. | Removes the `ctx.ctr` store in 4,666 `bdnz` loops and dead carry stores. A cheap slice of NL-1.4. | S | Low |
| NL-1.4 | **GPR, FPR and VR locals synchronized by the PowerPC ABI for the non-volatile set, and by callee live-in and clobber sets for the volatile set**, generalizing #467. NL-0.1 showed the title reads callee-left volatile registers (see Progress), so "dead after a call" needs the callee's own code, which the generator has.<br>• Before a call: store the registers the callee (transitively, for direct calls; every volatile register for indirect ones) reads before writing, and the dirty non-volatile locals.<br>• After a call: reload the return registers and every volatile register the callee may have written; the rest stay valid in locals.<br>• Full sync only at hooks that take `ctx`, `setjmp`/`longjmp`, SEH and functions NL-0.1 flags.<br>• The save/restore helpers become no-ops. | Static model: -47 to -55 % of `ctx` traffic, 12-14 % of host instructions. XenonRecomp and every PPC JIT surveyed (Cemu, RPCS3, Xenia, Dolphin) keep registers out of memory. Estimate: -15 to -30 % guest instructions. Needs NL-0.1 and NL-1.2. | L | High |
| NL-1.5 | **Strong symbols except a declared override list**, so Clang and ThinLTO can inline. Hidden visibility on Android. A host definition missing from the list fails the link, so the list can't be silently incomplete. Then measure ThinLTO again: #464 measured it while LLVM still refused every guest-function inline (`InlineCost.cpp`, "interposable"). | 12,736 functions have 8 or fewer guest instructions. 7.5 MB of Android dynamic symbol tables. Estimate: 3-6 % (PB-3.6), more after NL-1.4. | M | Low-medium |
| NL-1.6 | **Stack.** First, the r1 fast path for the FP, update, sign-extend and vector forms (58,444 sites, about 10 % of the six-channel biquad). Then plain (non-`volatile`) r1 accesses. Then non-escaping frame slots as host locals in host byte order. | Literature: SecondWrite 1 → 6.5 % on optimized inputs; WYTIWYG shows promotion can also lose, so keep a per-function switch. | S, S-M, then L | Medium |
| NL-1.7 | **Ship PGO keyed by guest address.** Emit `#line` equal to the guest instruction offset and use sample PGO (`llvm-profgen`), so a profile survives codegen changes. CI builds one profile per release; generation is deterministic for the one accepted XEX. | Measured: -1.4 to -5.5 % per guest thread (#464). It stayed opt-in only because profiles broke on codegen changes. | S-M | Low |
| NL-1.8 | **Use the player's CPU.** The build already runs on the player's machine. On CPUs that have them, compile for x86-64-v3 (MOVBE fuses load and byte swap; BMI2, AVX2) behind the existing start-up guard. | `bswap` is 4.7 % of host instructions. Unmeasured: measure cycles on the Deck (Zen 2) and the 5800X. | S | Low |
| NL-1.9 | **Smaller and faster to build.**<br>• Optional disassembly comments: 24.5 % of the source.<br>• `sub_8241A370` split or built at `-O1`.<br>• `cold` or `-O1` for functions no route executes.<br>• Dispatch entries for function starts only, 4 bytes each.<br>• `PPCFuncMappings` const in `.rdata`. | Shorter first builds (20-60 min today) and about 35 MiB less committed memory | S each | Low |
| NL-1.10 | **Fold read-only image data.** At least 19,900 float-constant loads become literals, with a start-up hash of the folded ranges as the guard. | Small-medium | S-M | Low-medium |

Below the line until earlier items are measured:

- **Guest registers as host arguments** (`preserve_none`). Instrew measured
  1.96 → 1.69 of native, but those conventions have no callee-saved
  registers, which suits guest non-volatiles poorly. Measure after NL-1.4.
- **Plain heap accesses.** High risk: a guest data race becomes a C++ data
  race. Do it only with NL-2.3 memory classes and a chaos-timing build.
- **Guarded devirtualization.** No hot `bctrl` site is known yet; NL-2.3
  counts them.

### NL-2 Reverse engineering that feeds the generator

| ID | Work | Why | Effort |
| --- | --- | --- | --- |
| NL-2.1 | **A versioned knowledge base in `config/re/`** (TOML, keyed by base address) for functions, types, globals, memory classes, call sites and libraries. Each entry carries a confidence, its evidence and a v4 address resolved by `map-fh1-v4-addresses.py`.<br>• Import the RE record's 104 rows, the 73 mod entries and the 467 guest addresses that sit only in backlogs.<br>• A legal lint rejects instruction runs and hex blobs.<br>• The generator emits a name table, so profiles and crash logs read `sub_82438EA8 crt.pow`. | Today 606 guest addresses are scattered across docs and config, 139 of them in the record. No signatures, no types, nothing the generator can read. | S |
| NL-2.2 | **A local Ghidra workspace**, rebuilt headlessly from the player's own dump. It uses Ghidra 12.1 with the Xenon360 loader (Apache-2.0, VMX128) and applies ShiftGlue's function boundaries, switch tables and vtables plus the knowledge base. It lives in `.local/re/` and is never committed. LLM bridges (GhidraMCP) can draft names, which stay at "guess" until a route or hook confirms them. | Every finding is re-derived from generated C++ today | S |
| NL-2.3 | **An RE build** (`PINYON_SHIFT_RECOMP_PROBE`). Probes in `REX_FUNC_PROLOGUE`, `REX_CALL_INDIRECT_FUNC` and the memory macros record:<br>• per-thread call counts;<br>• per-site indirect-call targets;<br>• stack offsets touched;<br>• memory region classes and cross-thread sharing per cache line;<br>• field offsets typed by the RTTI vtable at an object's base;<br>• argument values;<br>• the LR of each MMIO store.<br>`harvest.py` merges route output into the knowledge base. | Turns the recompiled game into the RE instrument. It produces the facts NL-1.4, NL-1.6 and the plain-heap item need. | M |
| NL-2.4 | **Library identification.**<br>• Read the XEX static-library header: the SDK parses it, nothing uses it.<br>• Cross-match titles the player owns (Forza Motorsport 3 and 4) with BSim or BinDiff, in local databases only.<br>• No legal XDK signature set exists. | Native replacements of whole library families need identity and contracts | M |
| NL-2.5 | **The class hierarchy.** Extend `vtable_scanner` to read the RTTI hierarchy descriptor, which it reads but ignores today. | Devirtualization candidates; a type for each object in the field census | S-M |

**Gating rule.**

- Dynamic facts may choose what to specialize.
- Indirect targets, argument values and library replacements may be used
  behind an exact guard or a code hash with verify mode.
- Facts that can't be guarded need static proof plus a checking build that
  passes the route corpus: register signatures, memory privacy and resume
  pruning.

**First RE targets, in order:**

1. The ABI and stack-switch census (enables NL-1.2 and NL-1.4).
2. Memory sharing and polling (enables NL-1.6).
3. Indirect calls and classes on the hot threads: the scene walk and the
   job dispatcher.
4. The audio path:
   - the XMA register-write sites;
   - whether the reverb and biquad output reaches anything but the
     speakers. If not, an exact SIMD port is the wrong bar: a port checked
     by `audiocapture` signal-to-noise with the save hash unchanged
     becomes acceptable.
5. The simulation and job-worker call trees.

The allocator and the CRT string helpers are not targets (#465, #468).

### NL-3 GPU: compile the display lists once

These items are already deferred in the
[desktop renderer backlog](DESKTOP_RENDERER_BACKLOG.md). This research
confirms they are the desktop lever and adds the shader-interface piece.

| ID | Work | Why | Effort |
| --- | --- | --- | --- |
| NL-3.1 | **DR-5.3: compile each `IDirect3DCommandBuffer` once.** Hook the runner `82416A00` and compile at creation or close, so the decoder scales with lists (about 1,200 a frame), not dwords (1-1.8 M). | The decoder is 7.4-8.4 ms a heavy frame | L |
| NL-3.2 | **DR-3.1: an O(1) "unchanged since last frame" test** per subsystem: texture bindings, vertex and index ranges, tile ownership | Every replay attempt so far was slower because validating a draw cost as much as deriving it | L |
| NL-3.3 | **A shader interface in the XenosRecomp style.** The guest register file per stage, read by address; bindless textures; one specialization mask. Emitted as an offline SPIR-V pack built at install from the disc corpus. | The constant gather is about 1,130 cycles a draw. The pack also ends start-up re-translation and shortens the 125 s preparation route. Bindless alone measured ±1.5 % on NVIDIA, so it pays only with NL-3.1/3.2 | M-L |
| NL-3.4 | **DR-4.1 and DR-4.2: constants by address, then GPU re-execution** of compiled lists (secondary command buffers or descriptor buffers) | Ceiling probe: recorder 10.4 → 3.7 ms on the heavy race start | L |
| NL-3.5 | **Surfaces sized by role and evicted when idle (LS-4.3); VMA blocks of 64 MB** (skate3 `f7d808a`, BSD-3) | 2.0-2.4 GB of VRAM at 2x/3x; returns freed memory to the OS | M |
| NL-3.6 | **Pipelines built when a display list is created or rewritten**, decoded off the hot threads | First-launch stutter: 5.7 s over budget after the warm-up route | M-L |

### NL-4 Lean runtime pieces

| ID | Work | Why | Effort |
| --- | --- | --- | --- |
| NL-4.1 | **XMA at the API.** Hook the guest XMA register-write sites, found from the MMIO handler's LR log, and call the decoder directly. Decode off the guest audio thread with read-ahead. | `MMIOHandler::CheckStore` is 22 % of the Odin audio thread inclusive; the trap and dispatch part is about 7 points | M |
| NL-4.2 | **Audio fixes from Edge and Canary.**<br>• Pump the audio off the global lock (Edge `12e3b4223d`, #416).<br>• NEON `ConvertFrame` with x64 rounding parity: Android and macOS truncate today.<br>• The XMA packet-boundary and loop-start fixes. | Android stutters and audio-thread CPU; bit parity across platforms | S each |
| NL-4.3 | **Kernel objects in the guest dispatcher headers**: atomics plus `WaitOnAddress`/futex, as UnleashedRecomp does (idea). The interrupt callback runs outside the global lock. | Android only: restructuring the lock measured 0.34 ms a frame on desktop | M-L |
| NL-4.4 | **Commit the physical heap on demand; trim idle pipeline workers** | Part of the 2 GB resident; measure with NL-0.3 first | S-M |
| NL-4.5 | **Async file reads** (Edge `c6cc761676` and its follow-ups) | Only if NL-0.3 shows per-read stalls on the Deck SD card or Android storage; desktop reads total 91 ms a run | M |

### NL-5 Quick ports from Xenia forks

All are BSD-3; keep the Xenia headers on any ported file. Each was checked
against the SDK.

| Port | Source | Why |
| --- | --- | --- |
| Primitive-conversion cache invalidation compares against the wrong bound (`primitive_processor.cpp:1513`) | Edge `1b0e9d00ea` | A rewritten index buffer can draw with stale converted indices; FH1's quad and rectangle lists are converted |
| Invalidate unwatched pages on protect, decommit and release (`xmemory.cpp` `TriggerCallbacks`) | Edge `5ddf045a83` | Page state persists across frames since schema 26 |
| SPIR-V main-loop switch fall-through (`spirv_translator.cpp:1485-1505`) | Edge `f145711a4a` | An NVIDIA device loss; relevant to #388 |
| Scalar ALU swizzle with three-source vector ops (`translator.cpp:1336`) | Canary `92ada8ebc0` | Scan the 3,349 shaders for the encoding first; bump the shader cache version |
| XInput subtype per device, with a per-slot wheel override | Canary `103257c5aa` | FB-2.1: the game sees a wheel |
| Deferred-overlapped delay 100 → 25 ms | Canary `8d2d80dfde` | About 0.1 s once at boot |

A free-running `V_COUNTER` (Edge `9d93773228`) is worth a log check: if
FH1 reads it, it may relate to #381.

### NL-6 Player-facing: online play

[Dyotson/RecompiledForzaHorizon](https://github.com/Dyotson/RecompiledForzaHorizon)
(MIT, ReXGlue-based, created 2026-10-10) is the first known working FH1
online implementation. It reports matchmaking, Rivals, car clubs and
shared free roam, using:

- a UDP tunnel for the game's ports 1000 and 1001;
- virtual `0.77.0.N` peer addresses;
- a rendezvous and relay server;
- a "Turn10.Horizon" title-services endpoint.

It targets the base executable, so every address has to be re-derived for
v4, and its addresses are someone else's analysis: leads only
(docs/LEGAL.md). It also needs a server that we or the players would
host. Effort L. Whether to pursue it is a product decision, not a
technical one.

## Progress

Dispositions of the items started so far, with the evidence. Static counts
are over the 260 generated x86-64 objects of the Windows Release build
(FMA3 baseline), before and after the change, with the pinned Clang 20.1.8
and `llvm-objdump`.

| Item | Outcome | Evidence |
| --- | --- | --- |
| NL-1.1 Windows | **Done.** The runtime maps every guest view through a placeholder (`VirtualAlloc2`, `MapViewOfFile3`) at its exact file offset, so the `0xE0000000` view sits where it belongs and `REX_PHYS_HOST_OFFSET` is `0` on Windows. A Windows older than 10 version 1803 is refused at start with a message. | All 625,228 select compares are gone from the generated objects. Together with NL-1.3 (the two were generated together): host instructions 17,733,702 to 13,717,318 (−22.6 %), generated `.text` 74.97 to 59.68 MB (−20.4 %); byte swaps, flush-mode writes and vector reversals unchanged. The select's share by the four-instruction estimate was 14.1 %, so about 8 % of the saving is NL-1.3's. |
| NL-1.1 Linux, Android | **Built, not run.** `PINYON_SHIFT_PHYSICAL_HEAP_4K_PAGES` (default on) compiles the offset to 0; `Memory::Initialize` refuses a kernel with larger pages. Every device in the lab uses 4 KB pages (Odin 2 Portal, Android 13; the Snapdragon 8 Elite tablets, Android 16; the Deck). | `getconf PAGESIZE` on the three Android devices: 4096. |
| NL-1.3 | **Done.** `ctr_as_local` and `xer_as_local` in both analysis files. | Counts above. Hooks that take `ctx` and `guest_native` verify read neither register. |
| NL-5.1 | **Ported** (xenia-edge `1b0e9d00ea`): a cached primitive conversion is dropped when any part of its index range is written, and a conversion in progress over a written range is not stored. | Correctness; the test compared against the range's end. |
| NL-5.2 | **Ported** (xenia-edge `5ddf045a83`): a guest protect-to-writable, decommit or release raises the GPU invalidation callbacks even with no watch armed, since page validity persists across frames. | Correctness. |
| NL-5.3 | **Ported** (xenia-edge `f145711a4a`): a translated shader's main-loop switch case jumps through the loop's continue block instead of falling into the next case, the pattern that lost NVIDIA devices. | Changes shader output; the Vulkan translation cache keys on the translator version. |
| NL-4.2 | **Ported.** The audio pump reads its client table under a mutex of its own instead of the global critical region, and the heap is never touched while it is held (xenia-edge `12e3b4223d`); ARM64 converts XMA frames and folds 5.1 to stereo with NEON, rounding and saturating as x64 does (`b899a97a7e`, `32177527fa`); a frame whose header crosses a packet boundary is counted (`adf56b76c4`), a loop start one bit short of a frame boundary is resolved to it (`5dd1cdbbf5`), and the work loop drains a partly delivered frame (xenia-canary `6bef1fbed1`). | Correctness and bit parity; the Android audio thread's cost is for the Odin to measure. |
| NL-2.1 | **Done differently.** The knowledge base is `site/findings/*.toml` (430 records with confidence and evidence, rendered by the site with an address index and `symbols.json`), which the repository already had. Added on top: `tools/re/kb.py` (`symbols` writes one address table with a names map; `check` verifies every `sub_X` a record names is a generated function start, base and v4; `lint` refuses disassembly listings and hex dumps), `tools/summarize-thread-samples.py --symbols` labels profiles with the recorded names, and `tools/tests/test_re_kb.py` runs the lint and the check. The two findings this research made (the fiber switch, XER and CTR) are recorded on the Executable page. | `check` found one record whose v4 field paired base and v4 addresses with an arrow, handled; the lint found none. |
| NL-0.1 | **Built and run; the ABI hypothesis failed.** `PINYON_SHIFT_RECOMP_ABI_POISON` generates the game with a check around every guest call (`rex/ppc/abi_poison.h`): the non-volatile registers are snapshotted before and compared after, and the volatile registers the ABI leaves dead at a return are overwritten with a value that names the register and the call site; an argument register still holding one at the next call is logged. | On `fh1-race-sustained` the non-volatile checks never fired (0 mismatches, two runs), but the build crashed on the simulation thread within two seconds: `sub_823F3048` calls `sub_823F2ED8` in a loop and sets r3-r5 but not r6, so the callee stores through whatever r6 its previous call left. The title does rely on callee-left volatile registers. **Consequence for NL-1.4:** non-volatile registers may live in locals synchronized by the ABI, but a call may not treat a volatile register as dead unless the callee's own code never reads it before writing it. The generator has the callee bodies, so it can compute each callee's live-in and clobber sets (transitively for direct calls, conservatively for indirect ones) and synchronize exactly those registers; the poison build, told the same sets, then checks the analysis instead of the ABI. The "argument still poisoned" log is noisy because it does not know each callee's arity (stale r5-r10 are reported at every call); the same sets fix that. |
| NL-0.5 | **Decided.** The generated units now compile with `-fno-strict-aliasing` (on) and without `-fasync-exceptions` (off, `PINYON_SHIFT_RECOMP_SEH` brings it back); `-ffp-model=strict` stays an option (`PINYON_SHIFT_RECOMP_FP_STRICT`). | Three hot partitions (the audio reverb's, the six-channel biquad's and the 27,503-instruction kernel's) compiled with each flag, no precompiled header: `-fno-strict-aliasing` produced byte-identical objects; `-ffp-model=strict` added 2.1 %, 1.5 % and 0.9 % host instructions; `-fasync-exceptions` added 0.3 %, 0.3 % and removed 0.8 %. No generated unit contains an SEH scope. |
| NL-1.8 | **Built as an opt-in variant**, not the default. `PINYON_SHIFT_CPU_BASELINE=v3` (preset `win-amd64-v3`, `build-preview.ps1 -CpuBaseline v3`) compiles for x86-64-v3 with a start-up guard for AVX2, BMI1/2, LZCNT, MOVBE and F16C. | Same three partitions: MOVBE replaced 20 % of the byte swaps in the two audio routines (677 and 714 `movbe` for 619 and 676 fewer `bswap`) and 0.6 % in the float kernel, for 0.8 %, 1.0 % and 0.1 % fewer host instructions. Too small statically to change the default; a cycle measurement on the Deck or the 5800X decides it. |
| NL-0.3 | **Measured.** New tools: `tools/measure-process-memory.py` (resident, committed and reserved bytes by region: guest views, dispatch table, each image, private, mapped) and `tools/summarize-startup.py` (time to each startup milestone from a runtime log). | **Resident memory in the race** (Windows, 1x, RTX 4080, working set 2,009 MB, private commit 1,868 MB, 101 threads): anonymous private memory 697 MB (host heaps and the driver), other mapped files 621 MB resident of 2,093 MB committed (the driver's and the content archives' mappings), the guest arena 577 MB (physical heap 248 MB through the A0 view plus 142 through the raw view and 12 through C0, the 64 KB virtual heap 78, the 4 KB heap 35, the XEX 34, the dispatch table all 28 MB), images 115 MB (the executable 52 MB). **Startup** (new build, from the first log line): arena mapped 0.87 s, function table 0.94 s, executables loaded 1.18 s, first guest instruction 1.19 s, first movie frame 2.6 s; the same within 0.1 s on the build before this work. The front-end stall and instruction-mix counters on the Deck and the Odin are still to do. |

## Order

1. **Now (S items, parallel):**
   - NL-0.1, NL-0.3, NL-0.5;
   - NL-1.1 (the select), NL-1.3, NL-1.8;
   - NL-5's first three ports and NL-4.2;
   - NL-2.1.
2. **Next:** NL-1.2 (fibers, then single entry), with NL-2.3 probes and
   NL-0.2. Then NL-1.5 and NL-1.7.
3. **Then:** NL-1.4, full register locals. Then NL-1.6.
4. **In parallel, a separate track:** NL-3.1 → NL-3.2 → NL-3.3 →
   NL-3.4, the desktop 1x lever, and NL-4.1.

A rough bound, as an estimate: NL-1.1 plus NL-1.4 would cut guest-thread
instructions on the Odin by between a quarter and a half, if their ranges
above hold. For scale, #431's r1 change (-17/-18 %) and #467's CR locals
(-11/-12 %) compound to about -27 % on the render and simulation threads.

## Corrections and other findings

- **Survey corrections** ([RECOMP_OPTIMIZATION_SURVEY.md](RECOMP_OPTIMIZATION_SURVEY.md)):
  - The `-ffp-model=strict` / `-fno-strict-aliasing` row says "Same", but
    the flags reach only the SDK's sources, not the generated units
    (NL-0.5).
  - The setjmp row says no addresses are set; `main-xex.toml` sets them.
  - The conditional flush-mode skip predates #466; only carrying the mode
    across labels is ours.
  - The three Canary options marked *unverified* exist:
    - `x64_extension_mask` fuses `vmaddfp`;
    - host/guest stack sync is JIT-only;
    - MMIO store recording is what our static `REX_MM_*` already does.
  - Xenia Edge's "guest fibers" are a full guest-thread scheduler on six
    host threads, not fiber parallelism. Still not applicable.
- **`docs/LINUX_PORT_BACKLOG.md`** says the large-code-model link has
  never run, while a 195 MB Linux binary is on record. The Linux x86-64
  build also still uses `-mcmodel=large`, although 75 MB of text fits the
  small model; that is worth a measurement.
- **Licence notices:**
  - ShiftGlue's source carries XenonRecomp-derived code (disassembler
    tables, config schema, `PPCContext`, VMX helpers), but no XenonRecomp
    MIT notice ships, and `THIRD_PARTY_NOTICES.md` lists only ReXGlue.
  - Comments in `include/rex/ppc/context.h`, `function.h`,
    `intrinsics.h`, `src/codegen/config.cpp` and
    `src/ui/vulkan/vulkan_presenter.cpp` credit UnleashedRecomp, which is
    GPL-3.0.

  Both need a check under [LEGAL.md](LEGAL.md).
- **Security:** `github.com/conventional-elanoides4623/pinyon-shift` is
  not a fork. It copies this project's commit subjects, and on 2026-10-12
  its README pointed a download button at a zip inside the repository.
  That is a common malware-lure pattern; nothing was downloaded.

## Sources

Research notes with full citations:
`.local/backlog-research/next-level-2026-10-12/` (codegen audit, runtime
and GPU audit, XenonRecomp/XenosRecomp lineage, translation literature,
RE and specialization, Xenia forks). Primary sources cited there include:

- [XenonRecomp](https://github.com/hedge-dev/XenonRecomp),
  [XenosRecomp](https://github.com/hedge-dev/XenosRecomp) and
  [UnleashedRecomp](https://github.com/hedge-dev/UnleashedRecomp);
- [Xenia Canary](https://github.com/xenia-canary/xenia-canary) and
  [Xenia Edge](https://github.com/has207/xenia-edge);
- Instrew ([VEE 2021](https://home.cit.tum.de/~engelke/pubs/2104-vee.pdf)),
  SecondWrite ([EuroSys 2013](https://terpconnect.umd.edu/~barua/anand-EUROSYS-2013.pdf)),
  WYTIWYG ([ASPLOS 2024](https://doi.org/10.1145/3620665.3640371));
- [`MapViewOfFile3`](https://learn.microsoft.com/en-us/windows/win32/api/memoryapi/nf-memoryapi-mapviewoffile3)
  and LLVM's inliner
  ([`InlineCost.cpp`](https://github.com/llvm/llvm-project/blob/llvmorg-20.1.8/llvm/lib/Analysis/InlineCost.cpp#L3070)).
