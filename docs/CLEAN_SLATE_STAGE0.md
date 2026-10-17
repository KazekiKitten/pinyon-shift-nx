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

## CS-0.4: true guest completion latency

The SDK's default-off, hot `gpu_true_fence_completion` probe submits and
waits for host GPU work on the recorder thread before `EVENT_WRITE_SHD`
fence stores, enabled scratch-register writebacks, command-stream
interrupts and `WAIT_FOR_IDLE`. Vulkan uses its existing submission-fence
wait, which first waits for the submission worker to have submitted the
fence; D3D12 uses its existing queue completion wait. Failure refuses the
guest signal. The existing `FlushCpuVisibleResults` only flushes resolve
readbacks, so it was not a general GPU completion wait. The ring read
pointer still describes decoding progress; it is not changed into a GPU
completion marker. This is a synchronous latency probe, not an asynchronous
completion scheduler or a shared guest/GPU arena.

**Gate failed, 2026-10-17.** The SDK implementation is commit `4d78764` on
`main`, on project source `e8bbbb81` (no subsequent application-source
change). Native Release builds use the existing base generated tree with
frozen codegen. Routes
`tools/cs/routes/cs04-{race,free}-ab.fh1test` toggle only this cvar and the
perf A/B marker. The race uses 300-frame windows from route frame 6000;
free roam uses 300-frame windows from frame 1800. Both use the pinned
`appdata-2026-09-27` seed (profile SHA-256
`CC8951E814DBC750AAC5C204772BEF84094847273849F216B1DF7462CDC314E4`),
copied into a private state for each run. Free roam remains parked; the
race drives. The race uses `fh1-gauntlet-entry-sync`'s longer button presses;
free roam holds the handbrake after entry. No builds ran during routes.

All measurements below are Vulkan, 1x, vsync off, with the same build on
both sides: Odin 2 Portal/installed Turnip V37 and Steam-launched Deck
LCD/RADV at the 60 limit; Ryzen 7 5800X/RTX 4080/NVIDIA 581.08 desktop at
the 120 limit. Deck ancestry proves a Steam launch, its power profile was
`auto` and gameplay clocks were 1,040-1,600 MHz. The SDK's D3D12 path was
compiled on Windows but not measured. Source, build logs and binary
fingerprints are `cs04-build-*-final.log`, `cs04-local-binaries.json` and
`cs04-deck-binaries.sha256` in `.local/codex-cs/`. The build directories'
older sidecar JSON files were stale after direct CMake rebuilds; their
October 15/16 revision/hash fields are **not** the provenance of these
runs. The fingerprint files and build logs are. The exact Android APK is
retained as `cs04-probe.apk`.

`tools/cs/summarize-fence-ab.py` uses the NN in-run method: drop the first
boot/loading window, discard the first 30 frames of each remaining window,
require 60 retained samples, then pair adjacent opposite windows. No
frame-time outliers are removed. Race results have five pairs, free roam
six; the side aggregates also include the final unpaired window. Means
and p99 use `frame_time_us`; slow frames here means over **20 ms** on all
devices. Counts, draw rates and every window are in
`cs04-{odin,deck,win}-{race-ab5,free-ab1}-summary.json`.

| Device / route / run | Mean ms, off → on | Change | p99 ms, off → on | Frames over 20 ms, off → on |
| --- | --- | ---: | --- | --- |
| Odin race / `race-ab5` | 16.68 → 20.27 | +21.49% | 17.29 → 24.42 | 0.30% → 53.61% |
| Odin free roam / `free-ab1` | 16.68 → 23.08 | +38.37% | 17.26 → 27.56 | 0.19% → 98.69% |
| Deck race / `race-ab5` | 16.77 → 48.21 | +187.52% | 20.77 → 57.33 | 1.64% → 99.54% |
| Deck free roam / `free-ab1` | 16.84 → 48.69 | +189.20% | 21.41 → 59.97 | 1.52% → 99.60% |
| Multivac race / `race-ab5` | 8.39 → 12.91 | +53.82% | 9.98 → 17.07 | 0.04% → 0.23% |
| Multivac free roam / `free-ab1` | 8.45 → 13.17 | +55.93% | 11.01 → 16.73 | 0.03% → 0.08% |

Paired frame-time costs (mean ± SE, ms): Odin race `3.59 ± 0.19`, free
`6.33 ± 0.12`; Deck race `31.68 ± 0.93`, free `32.02 ± 0.65`; desktop
race `4.70 ± 0.20`, free `4.76 ± 0.24`. The GPU-thread fence-wait counter
increased on the Odin race from 0.049 to 14.48 ms per frame and on the
Deck from 0.108 to 33.11 ms, confirming that the treatment awaited actual
host submissions. Draw counts on the race differed by +1.2% on Odin and
-3.2% on Deck, much smaller than the measured frame loss.

Controls `race-aa1` and `free-aa1` run the corresponding `*-aa` routes with
completion **off on both sides**, preserving the marker schedule. A/A
paired differences, ms ± SE: Odin `0.00023 ± 0.00017` race,
`0.00051 ± 0.00037` free; Deck `0.048 ± 0.050` race,
`-0.0048 ± 0.0125` free; desktop `-0.0025 ± 0.123` race,
`-0.0093 ± 0.096` free. All aggregate mean differences were under 1%.
The largest absolute A/A p99 shift was 2.32 ms on the Deck race, against
the treatment's 36.56 ms. Each device's raw A/A summary is retained too.

All twelve qualified A/B and A/A routes reached their scripted stop with
no hang or device loss. The existing race-HUD checker passes all six race
captures (`cs04-hud-checks.json`), and inspection of pre-treatment and late
race/free-roam captures found no new corruption. The fixture's car-select
thumbnails already show noise before treatment; that is not attributed to
true completion. The old free-roam
fixture's generic 55 Hz presentation / 80 Hz simulation floors reject
some runs, including controls capped at 60; those post-run failures are
retained, not called passes. They are not the CS-0.4 gate. Early `race-ab1`
to `race-ab4` attempts are excluded: incompatible output waits in a
wall-time script, a precreated Android output directory, missing Deck
shader storage, a short-press route that stayed in free roam, and an
unsuccessful brake setup that selected reverse. Only the later race-HUD
qualified route supplies race numbers.

This synchronous **whole-prefix** host-fence wait is conservative: it
also stops recording while the queue completes. The results reject this
implementation against the unchanged 3%/p99 gate; they do not prove that
asynchronous or stage-specific retirement must cost as much. They do
not authorize a shared arena. The diagnostic cvar remains off by default,
and CS-4 is held pending a different completion design and a new probe.

## CS-0.1: ordered session pilot

The default-off SDK pilot (`cs_session_mode=1` record, `2` replay,
`cs_session_path` filename, both restart-only) records a total order of
boundary observations. Mode 1 refuses an existing file. Mode 2 feeds back
recorded guest timebase, system-time, uptime and controller-state values;
it validates identities, kernel results, I/O results/digests and each PM4
hash. The first mismatch exits with status 86 and an expected/actual
boundary tuple. It does not continue with unrelated values. The same
binary is used for record and replay.

The log covers XThread starts, single/multiple/signal-and-wait requests
and results, event/semaphore/mutant signaling, timer APC firings, XFile
read/write status, size, offset and content digests, GPU fence writes and
interrupts. XThread-backed workers get their kernel thread ID; other host
threads use tag zero. I/O is reissued against the same immutable game and
pinned initial save, with results checked, rather than copying game
content into the recording. This is narrower than replaying arbitrary
external I/O. Directory queries, network results, host vblank scheduling,
host thread-pool arbitration, inline guest atomics and fast critical
sections are not fully intercepted. Wait logging **observes** ordering;
it does not force the host scheduler to reproduce it. Initial clock
epochs and the timer queue's host deadlines are not virtualized. These
are explicit limits of the cheap pilot, not claims that nondeterminism
outside the hooks is absent.

Every decoded PM4 header and payload, including IB links, nested buffers
and zero padding, contributes to a 64-bit FNV-1a hash, closed at `XE_SWAP`.
A separate count records the dwords in the same frame. This hashes packet
memory at decode entry, rather than merely counting draws or final
registers; concurrent mutation after that snapshot is not modeled.
The log flushes at every frame. `tools/cs/read-session.py` emits
counts and hashes, never input or I/O contents. Full guest-memory hashes
at every kernel synchronization were not added to this pilot; a dirty-page
snapshot design remains part of CS-1.

`tools/cs/session-self-test.cpp` links the real runtime without a game.
It records then replays a clock value and a 16-byte input state despite
different live values; boundary-order and PM4-hash negative controls exit
86; recording over the same file exits 86 and preserves it. The reader's
self-check rejects malformed/truncated records and oversize payloads.
This separates a broken log format from a real session-order divergence.

The game route `tools/cs/routes/cs01-race.fh1test` uses the qualified
Gauntlet entry and records from boot, with 60 wall seconds between the
`gauntlet-driving` and `gauntlet-end` captures. GPU true-completion stays
off. The recording and replay each start from a new private copy of the
same seed as CS-0.4.

**Gate failed, 2026-10-17.** Project source `c6333e00` (application C++
unchanged from `0f8f20b2`), SDK main `40666b3`, frozen base codegen, native
Release Windows and Android builds. Both use Vulkan, 1x, vsync off and a
60 fps game cap. Device/driver identities are those above. Builds finished
before routes started. Exact binary hashes are in `cs01-detail-binaries.json`;
APK SHA-256 `80253c185dd182358d19f22e6307ba81adb283e4cf458986140bae937dceab88`.
Build logs `cs01-build-{win,android}-detail.log` and
`cs01-build-linux-detail-retry.log` record the rebuild. The old generated
build sidecars still have stale metadata; they are not revision evidence.

Each device's `cs01-record2` completed the route. Both start/end capture
pairs show the race HUD and a 60-second race-clock interval
(`cs01-record2-captures.png`, `cs01-record2-hud.json`). These are recordings
from boot through the race, so the totals below include startup. Two
independent replays, `cs01-replay2` and `cs01-replay3`, each use a fresh
private seed copy and the **same binary and record2 reference** on that
device. They fail closed at the first identity/order mismatch:

| Device | Recorded bytes / boundaries | Recorded duration / PM4 frames | Replay2 first mismatch, zero-based | Replay3 first mismatch | Verified equal PM4 |
| --- | ---: | ---: | --- | --- | --- |
| Multivac / RTX 4080 | 1,082,406,224 / 27,056,475 | 161.179 s / 9,614 | 18: uptime expected, system-time actual | 5: uptime expected, system-time actual | 0 frames, 0 s |
| Odin / Turnip V37 | 985,542,720 / 24,634,907 | 164.159 s / 9,555 | 1: uptime expected, system-time actual | 3: uptime expected, system-time actual | 0 frames, 0 s |

All four actual/expected tuples have host-thread tag zero, key zero and
zero payload size. The mismatch is **event order**, not an observed PM4
hash mismatch or a differing returned time value: replay substitutes clock
values only after the boundary identity matches. On Windows the wrapper
reports intentional exit 86; Android's flushed runtime log records the
same fail-closed path. Expected/actual tuples and boundary indices are in
`desktop/cs01-replay{2,3}.state/logs/runtime.log` and
`odin/cs01-replay{2,3}/logs/runtime.log`. Trace summaries and per-frame
hashes are `cs01-{win,odin}-record2-summary.json`; raw references have the
same prefix and `.bin` suffix. Raw traces are local only.

Source inspection explains why scalar playback is insufficient: the kernel
updates its guest timestamp bundle from a 1 ms **host** repeating timer
(`xboxkrnl_module.cpp`), while guest system time is also queried during
XThread construction (`xthread.cpp`). Their startup interleaving is not
controlled. The log does not retain query call sites, so these particular
call paths are an inference from the startup context, not a captured call
stack. The observed class is the differing order of clock-boundary types.
The broad global clock hook also includes host work tagged zero; a future
oracle must distinguish that work from guest queries.

Initial `record1/replay1` attempts had the same early order failure
(Windows boundary 4, Odin 26), but detailed tuples went only to stderr,
which Android did not retain. The logger was fixed and both recordings
repeated before using the table above. No record/replay pair crosses a
binary change. Real-runtime positive playback, order/hash negative controls,
exclusive-create protection and disabled-mode no-file checks pass with the
final runtime (`cs01-self-test-detail.txt`); release-contract tests: 40 pass.
The full tools suite before the logging-only correction: 534 pass, 6 skip,
111 subtests. No performance gate is inferred from recording overhead.

This is a first-divergence census, **not an exhaustive discovery of every
source in the race**. Replay never reaches its first PM4 comparison, so
later scheduling, input, I/O, memory and GPU equality remain untested. No
memory hashes were collected. Do not claim a 60-second deterministic
session or authorize CPU/GPU rewrites against this pilot as an oracle.


A full CS-1 design needs the following before PM4 equality can serve as an
oracle. These are coverage gaps identified from the implementation, not
additional experimentally observed mismatches after the first failure:

| Source | Pilot coverage and required design |
| --- | --- |
| Host scheduling | Log order only; deterministic execution grants must arbitrate thread starts, wait returns and signaling. A log mutex orders observations, not the guest instructions between them. |
| Time | Returned scalar values only; use a virtual epoch and shared logical clock for timer deadlines, sleeps, vblank, GPU interrupts and their delivery order. Host polling must not consume guest clock records. |
| Identity | Kernel thread IDs and numeric boundary keys; use stable logical thread/object IDs and query-site identities, including host workers currently tagged zero. |
| Guest shared memory | No interception of inline atomics/fast critical sections or arbitrary races; deterministic scheduling plus dirty-page snapshots at synchronization points is needed. No memory-equality claim was tested here. |
| I/O | XFile operations and content digests observed, actual I/O reissued; capture external results, directory/metadata queries, network and entropy inputs, and isolate writes. Identical pinned files do not cover arbitrary I/O. |
| Input | Controller values replayed at intercepted calls; wall-time route/UI events still need a logical schedule and call identity. |
| GPU | Decoder packet snapshots, fence writes and interrupts observed; virtualize completion/vblank order and retain the memory each packet consumes. A 64-bit PM4 hash alone is not a guest-state proof. |
| Timers | APC firing observed but host deadlines and dispatch not controlled. Neither trace recorded a `timer_fire` event; that path has no device replay coverage. |

Stage 0 does not implement that scheduler, memory oracle or reference
interpreter. Failing this pilot rejects the cheap ordered-value replay
premise, not the feasibility of a deliberately deterministic runtime.
