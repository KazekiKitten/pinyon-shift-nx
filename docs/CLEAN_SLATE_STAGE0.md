# Clean-slate Stage 0 evidence

These are probes of the premises in [CLEAN_SLATE_RESEARCH.md](CLEAN_SLATE_RESEARCH.md),
not changes to the default runtime. Unestablished gates are not passes.
Local counts and device output are in `.local/codex-cs/`; they contain no
committed game code. No remote was pushed.

## CS-0.2: observable context state

**Gate not established, 2026-10-17.** The multivac analysis ran on the base
generated tree at project `ebbf959`, SDK `79d3e6f`. The tree was last
generated 2026-10-16; its concatenated partition SHA-256 is
`f73cb4edadf3461d014c18601b66bb28b1ef0b2c6f15aa155fe46628465c4613`.
`tools/cs/ctx-publish-sets.py` excludes reference copies and analyzes 76,257
`sub_` bodies, 209 context slots, 3,701,893 source load expressions and
2,725,935 source store expressions. These are source expressions, not host
instructions and not deletions.

The script builds a CFG from the emitted labels and branches and solves
may-read-before-full-write sets to a fixed point over direct calls. Partial
slot writes preserve the old slot. Native/context escapes, resume switches
and all 48,100 unresolved indirect call sites read everything. Callees are
not assumed to kill caller state, so the summaries are conservative, not
exact publish sets. The historical `.local/re/probe/race-summary.json`
contains observations at 18,017 indirect sites; observed targets are not a
proof of the possible vtable targets. No sound call-site vtable resolution
artifact was found. The script reports this as unknown, not zero targets.

For a compiled-code cross-check, it streams NDK r29 `llvm-objdump -d
--no-show-raw-insn` over `out/build/android-arm64-release/libmain.so`
(2026-10-16), retaining only counts. It recognizes AArch64 context-base
copies, counts pair loads/stores as one instruction, and clears speculative
state at branches. Only full GPR/LR/CTR stores are publication candidates.
A candidate is a store before a direct call to a callee that cannot observe
that slot. It can be **deferred**: a later observer may still require it.
It is not a net deletion, and host register pressure has not been modeled.

| Root (base address) | Direct closure, functions | Identified ctx loads / stores, static | Publication deferral candidates / host instructions, static | Same ratio, weighted by historical global race calls (estimate) |
| --- | ---: | ---: | ---: | ---: |
| Render `825A6320` | 1,369 | 24,272 / 38,327 | 2,139 / 245,359 (0.87%) | 0.48% |
| Simulation `8255AE10` | 6,210 | 116,581 / 188,289 | 12,662 / 1,089,757 (1.16%) | 0.55% |
| Audio `82FB4AF8` | 14 | 64 / 104 | 8 / 524 (1.53%) | 2.82% |

These closures overlap and omit indirect reachability. Global function call
counts cannot attribute a shared callee to a particular thread; the audio
closure is especially incomplete. The binary and historical call probe
are not a matched build. Accordingly none of these ratios is a hot-thread
instruction saving or evidence against the 15% gate. Missing evidence:
matched per-thread/per-edge call counts, sound indirect target sets, callee
must-write summaries, return demands and an instruction census after exact
publishing. **Do not authorize CS-2 from this census.**

Reproduction (PowerShell, repository root):

```powershell
.local/toolchain/python-3.13.15/python.exe tools/cs/ctx-publish-sets.py --self-test
.local/toolchain/python-3.13.15/python.exe tools/cs/ctx-publish-sets.py `
  --generated .local/generated/default --calls .local/re/probe/race-summary.json `
  --binary out/build/android-arm64-release/libmain.so `
  --objdump-executable C:/Users/neri/AppData/Local/Android/Sdk/ndk/29.0.14206865/toolchains/llvm/prebuilt/windows-x86_64/bin/llvm-objdump.exe `
  --output .local/codex-cs/ctx.json
```

The self-check covers a callee reading a caller's volatile `r6`, a write
before a call, a conditional write, a partial write, recursion and an
unresolved indirect call. No generated code is changed.

## CS-0.3: driver capabilities

**Extension gate passes literally on the Deck; graphics pipeline switching
does not, 2026-10-17.** Standalone `tools/cs/vulkan-probe.cpp`, built from
project `ef46d6c4` plus the probe, using SDK `79d3e6f`'s Vulkan headers.
It queries advertised extensions and their complete feature/property
structures with `vkGetPhysicalDeviceFeatures2` and `Properties2`. It does
not execute generated commands. Zero fields for an absent extension mean
not queried, not a driver-returned limit. Full JSON: `vulkan-{multivac,deck,odin,mac}.json`
in `.local/codex-cs/`.

| Device / actual driver | EXT DGC / feature | Pipeline execution-set limit / pipeline-binding stages | NV DGC / shader groups | Placed map: placed / range / reserve; alignment |
| --- | --- | --- | --- | --- |
| Multivac, RTX 4080, NVIDIA 581.08 | yes / yes; dynamic layout yes | 16,384 / `0xFF` (graphics and compute) | yes / 16,384 | absent |
| Steam Deck LCD, RADV Mesa 24.3.0-devel `aef01ebd12` | yes / yes; dynamic layout yes | 4,096 / `0x20` (**compute only**) | absent | yes / no / yes; 4,096 bytes |
| Odin 2 Portal, Adreno 740, Turnip Mesa 26.3.0-devel `a995eaeda4` (installed V37) | absent | unavailable | absent | yes / no / yes; 4,096 bytes |
| Minivac, M4 Pro, MoltenVK 1.4.1 used by the game | absent | unavailable | absent | absent |
| Astra | not measured: no Astra in `adb devices` or the reachable mDNS endpoints (those identify as RG Rotate and Shield TV) | unknown | unknown | unknown |

The EXT maximum sequence counts are 4,194,303 on NVIDIA and 1,048,576 on
RADV; token limits 32 and 128; token offsets/strides `UINT32_MAX` on NVIDIA
and 2,047/2,048 on RADV. Both report input modes `3`, transform feedback
and multidraw-count support. RADV's general stages mask is `0x3FFF`, but
the **pipeline-binding** mask is only `0x20`, and shader-binding mask zero.
NVIDIA reports `0xFF` for all three stage masks. General DGC support is
therefore insufficient to authorize the proposed graphics execution sets
on the Deck. The Odin needs the existing recorder fallback. Do not assume
a newer Mesa's features from its extension name on an installed driver.

`tools/cs/metal-probe.mm` separately allocated a two-command render ICB
on the M4 Pro with `inheritPipelineState=NO`, built a pipeline with
`supportIndirectCommandBuffers=YES`, and bound it in both commands.
Allocation and binding succeeded (`metal-mac.json`); GPU execution and a
compute-generated sequence were not tested. MoltenVK's extension result
must not be inferred from native Metal support. The Vulkan loader initially
returned `VK_ERROR_INCOMPATIBLE_DRIVER` without its ICD manifest; querying
the exact game's `rexglue-artifacts/libMoltenVK.dylib` directly succeeded.

On the Odin, the standalone binary uses the game's adrenotools namespace
hooks with a read-only copy of the **installed** driver, SHA-256
`b6d445f512d15bb94be3d46bb2e2d27f604f161bf7400f32ed6008de59844c7f`.
It runs in `/data/local/tmp/cs-stage0`, not in the player's state. The
hooks need `libc++_shared.so` beside them; the first attempt without that
dependency failed to load, then passed after copying it into that private
directory. No driver or player configuration was changed.

Build with C++20 and `-O2`, including
`thirdparty/shiftglue-sdk/thirdparty/vulkan-headers/include`:
Clang 20.1.8 on Windows; WSL clang with `-ldl -static-libstdc++
-static-libgcc` for the native Deck executable; NDK r29 clang with
`--target=aarch64-linux-android33 -static-libstdc++ -ldl -llog` plus the
existing `libadrenotools.a` and `liblinkernsbypass.a` and adrenotools include
directory for Android. Desktop/Deck take an optional loader path. Android
takes `driver-directory/ hook-directory/ library-name` for the custom
driver. Metal builds with `clang++ -fobjc-arc -framework Metal -framework
Foundation`. All probes exit nonzero on API/load failure.

The distinction between general DGC and pipeline binding follows the
[Khronos DGC specification](https://docs.vulkan.org/spec/latest/chapters/device_generated_commands/generatedcommands.html).

## CS-0.5: placed device-memory mapping

**Pass on both yardsticks, 2026-10-17.** The extended standalone probe
(`bc124685` plus `tools/cs/placed-map.h` and `placed-check.comp`; same
drivers and SDK headers as CS-0.3) allocated 536,870,912 bytes of
host-visible, host-coherent `VkDeviceMemory` and bound a storage buffer.
It first reserved `[0x200000000, 0x220000000)` with `PROT_NONE` and
`MAP_FIXED_NOREPLACE`, verified that it owned that exact range, then called
`vkMapMemory2KHR` with `VK_MEMORY_MAP_PLACED_BIT_EXT` and the reserved
address. The returned address matched. This is a whole-allocation map,
requiring no `memoryMapRangePlaced` feature.

The CPU wrote all 134,217,728 words with an index-dependent pattern. The
compute shader read **every word** in sixteen 32 MiB descriptor ranges
(respecting `maxStorageBufferRange` and dispatch limits), accumulating
mismatches in a separate coherent result buffer. HOST-to-COMPUTE and
COMPUTE-to-HOST barriers plus a host fence wait guard the result. Each
device returned zero mismatches. The probe unmapped with
`VK_MEMORY_UNMAP_RESERVE_BIT_EXT`, released the reservation and destroyed
its allocations. These tests never attach to the game or its save.

| Device | Allocation / checked bytes | Memory type / flags | Result | Evidence in `.local/codex-cs/` |
| --- | ---: | --- | --- | --- |
| Deck LCD / RADV `aef01ebd12` | 536,870,912 / 536,870,912 | 2 / `0x6` (visible, coherent; **not device local**) | 0 mismatches | `placed-deck.json` |
| Odin / installed Turnip `a995eaeda4` | 536,870,912 / 536,870,912 | 0 / `0x7` (device local, visible, coherent) | 0 mismatches | `placed-odin.json` |
| Multivac / NVIDIA 581.08 | not attempted: extension absent | unavailable | unsupported | `placed-multivac.json` |
| M4 Pro / MoltenVK 1.4.1 | not attempted: extension absent | unavailable | unsupported | `vulkan-mac.json` |
| Astra | not reachable | unknown | untested | CS-0.3 |

A negative-control shader deliberately reports the first word as wrong
while checking the same entire range. Both devices reported exactly one
mismatch and exit status 2 (`placed-{deck,odin}-negative.json`). Thus the
zero counts are not from an unexecuted dispatch or an unread result buffer.
No latency or bandwidth claim is made from these single functional tests.
RADV's first matching type is system/GTT memory, so this does not prove
that a particular device-local heap can replace the mirror without a
bandwidth or residency cost. Guest aliases, page permissions, write watches
and CPU/GPU lifetime synchronization remain untested. CS-0.4 is still
required before CS-4.

Compile `placed-check.comp` with the existing glslang tool:

```powershell
out/build/glslang-tool/StandAlone/glslangValidator.exe -V --target-env vulkan1.1 tools/cs/placed-check.comp -o .local/codex-cs/placed-check.spv
```

Add `--placed <shader-path>` to the CS-0.3 executable's arguments. The
placement/reservation code is implemented for Linux/Android; unsupported
devices are only queried. The reservation uses no overwriting fixed map
until the probe has successfully reserved and checked its own range.
See the [Khronos placement contract](https://docs.vulkan.org/refpages/latest/refpages/source/VkMemoryMapPlacedInfoEXT.html).

On multivac (Windows 11 Pro `10.0.26200`), a placeholder plus
[`MapViewOfFile3(MEM_REPLACE_PLACEHOLDER)`](https://learn.microsoft.com/en-us/windows/win32/api/memoryapi/nf-memoryapi-mapviewoffile3)
exists for a data/pagefile section handle. That does **not** establish a
route for an arbitrary D3D12 allocation: a D3D12 shared-heap handle is not
documented as such a mappable section, and `ID3D12Resource::Map` does not
take a requested host address. Microsoft's
[`OpenExistingHeapFromFileMapping`](https://learn.microsoft.com/en-us/windows/win32/api/d3d12/nf-d3d12-id3d12device3-openexistingheapfromfilemapping)
provides a special diagnostic system-memory heap from a section, with
resource/flag restrictions; it is not a general export-and-remap guarantee
for the game's GPU allocation. No D3D12 code was run. The plan's placeholder
route remains a platform-specific hypothesis, not a pass from this Vulkan
test.
