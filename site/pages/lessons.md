---
title: Lessons
section: Internals
order: 7
description: What Pinyon Shift's work on Forza Horizon suggests for other Xbox 360 static recompilations, including the ideas that were measured and didn't pay off.
---

# Lessons

What this project would tell the next Xbox 360 recompilation, in rough order of how much time each would have saved.

## Measure the game before writing a renderer

A census of what the game sends the GPU (render target configurations, resolve kinds, texture formats, primitive types, side effects) turned "emulate Xenos" into a bounded list. A renderer that handles exactly that list, and refuses anything else with a logged reason, was smaller and much faster than the general path it replaced. Keep the census tool: every new route is checked against it. See [Native renderer](renderer.md#why-a-game-specific-renderer).

Replace the parts where emulation is expensive (render targets, EDRAM, resolves, clears) and keep the parts that already work (shader translation, the texture decoder). A rewrite that started from "render six draw families natively" was slower than emulation and fell back on unseen scenes; the version that worked covered every surface and resolve the census found.

## Find where the frame actually goes

Profile before optimizing generated code. Here the guest threads were flat, with no function above 3 %, and at 1x the limit was the host thread recording GPU commands: about 1.6 µs per draw at 5,000 draws a frame. Halving that per-draw cost was worth more than any change to code generation.

Most per-draw savings came from noticing that inputs hadn't changed. 58 % of draws changed only shader constants, so caching pipeline, binding and constant derivation behind a state epoch paid off repeatedly. Replaying whole recorded draws did not: proving a recorded draw is still valid cost as much as deriving it. Once each subsystem got an O(1) unchanged-since-last-draw test (fetch constants written, a texture usage generation, a per-state memo), skipping the stages it covers saved 8 % of a draw. What remains is spread over about 20 small steps, so per-draw reuse has a floor, and only replaying whole buffers on the GPU goes below it.

## Waits are performance

The largest CPU savings outside the renderer came from how the host waits, not from translated code:

- The game's GPU fence poll loop, turned into a short spin and a block: −15 % process CPU.
- A spinning timer thread, a spinning render idle loop and polled multi-waits, each turned into a blocking wait.
- Windows rounds sub-millisecond sleeps to yields; a yield that returns at once can expose a race the console's scheduler hid.

## Let the calling convention bound the state you sync

Keeping guest registers in host locals only pays if the syncs with the register file are cheap. Writing every local back and reloading it around each call cost as much as it saved. The guest ABI already says which state survives a call. On PowerPC that is cr2–cr4 among the condition fields, so a call or return writes back only those and reloads nothing. That turned a measured no-gain into 11–12 % fewer instructions on the hot threads. Keep the full sync only where code reads the register file directly: hooks, `setjmp`/`longjmp` and exceptions. See [Recompiler](recompiler.md#what-the-generator-emits).

The same reasoning applies to tracked modes such as the float flush mode: a small dataflow pass over the generated function, meeting the state of every path into a label, removed 29 % of the toggles.

## Check the calling convention before trusting it

Keeping guest registers in host locals pays only if the synchronization with the register file is bounded by what the callee can see, and the natural bound is the calling convention: volatile registers are dead after a call. A checking build tested that on the race route by poisoning every volatile register after every call with a value naming the register and the call site. It crashed within two seconds: one function calls another in a loop without setting the fourth argument again, so the callee stores through whatever its previous call left in r6. The non-volatile registers, by contrast, were preserved by every call checked. So the convention bounds the callee-saved state, not the caller's: a generator may only drop a volatile register at a call when the callee's own code never reads it before writing it, which the generator can compute from the callee bodies it has. See [NEXT_LEVEL_RESEARCH.md](https://github.com/arcanite24/pinyon-shift/blob/dev/docs/NEXT_LEVEL_RESEARCH.md).

## Find the API behind a kernel primitive

Generated functions carried an entry switch so the runtime could resume them at a return address, because the game switches stacks through a kernel call that abandons the host call chain. The kernel call had exactly two callers, and reading them showed the OS API they implement: `SwitchToFiber`. The runtime already had host-fiber versions of the five fiber functions; mapping the game's copies onto them made every generated function single-entry, removed 342,683 switch cases and 7.4 % of the generated host instructions, and let Clang see reducible loops. A primitive the runtime emulates at the kernel level usually belongs to a small, well-documented API one layer up, which is cheaper to serve whole than to emulate underneath. See [Recompiler](recompiler.md).

## Ask why an inherited offset exists

The largest instruction class in the hottest generated functions was not game work. It was a select that added 4 KB to every guest address at or above `0xE0000000`, inherited from the emulator's memory layout: Windows' classic view-mapping call only places a view at a 64 KB file offset, so the view that should start 4 KB into the physical heap was mapped short and every access paid the difference. Newer placeholder views accept any page-aligned offset. Mapping the view where it belongs removed 625,000 selects and, with two volatile registers moved into locals, 22.6 % of the generated host instructions and 20 % of the code. Before optimizing translated code, check what each fixed cost in the access path is for and whether the host still needs it. See [Runtime](runtime.md#guest-memory).

## Port to a second architecture early

ARM found bugs x86 hid:

- **Memory ordering.** x86 is strongly ordered, so dropping the guest's barriers was harmless there. On AArch64 they had to be emitted as fences.
- **Page size.** 16 KB pages broke the `0xE0000000` view offset and the write-watch protection, which assumed one guest page per host page.
- **Drivers.** Each mobile driver needed its own workaround, and frame replay on two devices was the fastest way to bisect them.

## Fix frame rate with the game's own clock

Running above 30 fps needed no engine changes beyond faster vblanks: the game already integrates a real time delta. What remained were systems that add a constant per update. They were found by comparing guest memory snapshots at 30 and 120 fps and trapping writes to the values that drifted. Gate every such change on simulation time against real time, pose drift and the save's hash.

## Methods that held up

- **Pinned saves.** Scripted routes from a frozen copy of a save, never the live one, so results don't depend on progress.
- **Interleaved pairs.** The same build drifts about 4 % between batches. Compare A and B inside one batch, and on hot handhelds inside one run.
- **Frame replay.** A dumped frame replays deterministically on any device, to 0.02 ms. It turns "slower on device X" into a bisectable problem.
- **Knock-outs over timestamps.** Per-phase GPU timestamps distorted the phases they measured.
- **Validation layers in routes.** The AMD device loss in 0.4.0 was a threading bug the validation layer reported directly.
- **Normalize the render thread by what it drew.** Six alternating runs of the race route on the Odin varied from 953 to 1,503 draw calls a frame (traffic and weather), and the render and decoder threads' instructions followed the scene, not the build. The simulation thread does not depend on the scene and separated two builds at 5.6 % with three runs each; the render thread needs instructions per draw call, a replayed frame, or many more runs.
- **Instructions, not CPU time, across builds.** CPU time per guest thread is bimodal between runs of the same build. Retired instructions a second per thread, sampled at a fixed frame-rate limit, separate builds within four runs each.
- **Inclusive profiles from frame pointers.** `simpleperf record --call-graph fp` gives caller totals on Android without a profiling build; about 1 % of chains break. Rank callers this way before porting a leaf.
- **Train and measure PGO on different routes**, so the profile can't fit the measured run.
- **HDR on Android: check the layer, not the screenshot.** Android 13 lists no HDR10 color space to Vulkan even on an HDR10 panel; a 10-bit swapchain with `ANativeWindow_setBuffersDataSpace(ADATASPACE_BT2020_PQ)` gets one. `dumpsys SurfaceFlinger` shows the layer's data space and whether the display entered its HDR mode; `screencap` tone-maps the layer to SDR and makes correct HDR look dark. Read the composer's own table at the end of that dump too: on a panel mounted portrait, a landscape layer goes through an 8-bit rotator and is tone-mapped to SDR before it, so HDR10 only reaches the panel from a swapchain pre-rotated with the surface's `currentTransform`.
- **Check what the pinned host tools link.** LLVM's Linux release builds `ld.lld` against `libxml2.so.2`. libxml2 2.14 renamed it `libxml2.so.16`, so on SteamOS and Arch the linker couldn't start, and every compiler check failed with "unable to execute command". The tools that need it now run through wrappers that load only that library and its ICU from the sysroot. Try a new pin in a current Arch container before release.
- **Fix the order of anything you hash.** The DLC payload digest hashed a sorted file list, and Python sorts paths without case on Windows but with case on macOS and Linux. Rally verified on Windows and failed everywhere else with the same files. The digest now sorts the Windows way on every platform, which keeps the published digests valid.
- **Check that a developer option has a reader before using it.** Retail builds often keep the developer option parser and drop the code that used an option. FH1 parses `eventrestrictions` and `chooseillegalcarforevent`, but none of the 356 callers of the option object's getter reads them. A scan for loads from the getter's result, checked against options known to work, settled this without a run. The trainer patches the game's restriction parser instead.
- **Take another project's instruction tests, then audit them.** xenia-canary's PPC tests multiplied the suite by 1.7 and found gaps on the first run, but a third of the first failures were the harness, not the recompiler: a test that writes FPSCR left the host rounding toward zero for every later test (reset the FP environment per test), and a label repeated in two files bound a case to the wrong function. Of what remained, more cases had expected values that contradict their own inputs (a load of `0xAB` expecting `0`) than real differences. Keep those in a skip list with the reason on each line, so the suite stays green and the record stays honest.
- **Make the test car fail the limit you test.** The first event the route reached was one the save's car already qualified for, so the stock and the cheated runs looked the same. A database mod that limited that event to 1980s cars made the stock game refuse the car, which is what the cheat then had to change. A second mod that limited the class showed that the class is applied by a different function, which needed a hook of its own.
- **Trace the mechanism, not only the outcome.** To show that FH1's rubber-banding was off, the first idea was gap over time with the player waiting on the grid. Over 100 s it was noisy: some AI drivers stalled in both runs, and the stock AI reached 1 km about as fast as the fair AI. Logging each AI controller's own state twice a second settled it. In stock, every AI that got ahead spent most of the race in a rubber-band mode with its torque cut to 0.6. With NO RUBBER-BANDING, no AI did. The game's state machine says what the AI does; the outcome also depends on traffic and crashes.
- **Never quote one GPU's saving for another.** The same switch saved 8 % on one GPU and nothing on the next.

## What didn't pay off here

Negative results, so they aren't retried without a new reason:

| Idea | Result |
| --- | --- |
| CR fields in C++ locals, synced at every call | binaries 13–26 % larger for no gain; syncing by the calling convention instead paid (see above) |
| Building pipelines when a display list is created, ahead of its draws (NL-3.6) | a pipeline needs the render target formats and blend and depth state a list inherits from whoever runs it, and 96 of the 233 pipelines a first race still creates after preparation differ from stored ones only in that state; the most any approach could save is the first launch's extra 6.7 s over budget at two loading moments, once per install, since stored pipelines persist |
| Non-volatile GPRs, FPRs and vector registers in C++ locals (`non_volatile_as_local`) | correct only with the save/restore helpers inlined and every written local published to `ctx` at calls and returns, because the game reads a caller's register through `ctx`, also from functions reached indirectly; that made `.text` 66 % larger and guest code 20-27 % slower on the render and simulation threads at the same frame rate; kept as an off option |
| Hooking the guest XMA API to avoid a "trap" on every audio register write | there was no trap to avoid: the generator recognises the register window statically and emits those stores as direct calls into the decoder; the cost was the decode done inline on the audio thread. Moving it to the decoder thread (an SDK cvar) cut the guest audio thread 15 % on the desktop and 21 % on the Odin without touching guest code. Check how a hardware access actually reaches the runtime before designing around it |
| Canary's scalar-ALU swizzle fix (`b` from Z under a three-operand vector op) | no FH1 shader is affected: of 478,372 ALU instructions in the 12,846 disc shaders, none co-issues a scalar operation with `mad`, `cnd*` or `dp2add` (the XNA compiler never shares source 3) |
| Trusting a byte-match for a small function's title-update address | the five XAPI fiber thunks "mapped" to their base addresses in v4 (they sit 0xC1E80 higher); the v4 build then hooked five unrelated functions and failed to load. Check a small function's mapping by its cross-references |
| Guest stack accesses without `volatile` | 1.5 % fewer host instructions statically, but the race route ran 7-9 % slower on the desktop (108-110 against 117-119 fps median, worse p99); kept as an off build option |
| A free-running `V_COUNTER` (Edge) | FH1 never reads it: a race reads only `CP_PROG_COUNTER` and the vblank status through the register path (one-time read log, `gpu_log_register_reads`) |
| ThinLTO on the generated code | neutral on guest-thread instructions while the weak thunks blocked inlining; with direct calls on the strong bodies it inlines (code +8 %, instructions +12 %) but the desktop route sits at its frame-rate cap either way, so the Odin decides |
| More CRT functions as native code | the remaining candidates are 0.02 % each in a race |
| Float constants read by register number from a heap of 16-register pages, a draw copying only the pages written since (NL-3.3) | Forza Horizon writes new constant values nearly every draw: 1.9 page runs a draw were dirty and 0.03 came back unchanged, so pages copied 650 bytes a draw against 490 for packing just the constants a shader uses. The constants descriptor set got cheaper, but the heavy race recorder went from 7.5-7.7 to 7.9-8.5 ms (RTX 4080, 1x race, 3 rounds). Count how often a title's constants repeat before building constants by address |
| A native guest heap allocator | 0.05 % of a race, inclusive |
| Write-watches at 64 KiB | 7 write-watch faults a frame; the fault path is under 0.5 % |
| Reading the physical offset once per function | 3.6 MB smaller library, no runtime change |
| Honouring guest thread affinities, MMCSS, latency-critical placement | no consistent gain |
| Restructuring the global lock on desktop | 0.34 ms blocked per frame, not worth it; on Android, moving I/O off it was |
| Recorder replay, templates, segment replay | slower, or −0.3 % against a −15 % goal |
| Bindless textures on NVIDIA | ±1.5 % |
| Forcing tiled on-chip rendering on Adreno | about twice as slow |
| `VK_KHR_present_wait` | worse spacing |
| Store-op tuning, render-area trimming on tilers | too few cases, or the driver already did it |
| Bloom, motion blur and depth of field off | no measurable saving |
| No free-roam traffic, shorter grass, no crowd, no shadows from other cars (`AIOpenWorld.xml`, `TrackSettings.xml` by mod) | no change in frame or GPU time beyond run-to-run spread on the reference desktop, and nothing visible; untested on a weak machine |
| Muting the track reverb in its XML | the reverb is still computed; no change in audio-thread CPU |
| `-ffp-model=strict` on the generated code | 1–2 % more host instructions in the hot partitions, for a reordering across MXCSR writes never observed; kept as an option |
| `-fasync-exceptions` on the generated code | no generated unit has an SEH scope; the flag moved code size under 1 % either way, now off |
| x86-64-v3 (MOVBE, AVX2, BMI) for the generated code | MOVBE replaced a fifth of the byte swaps in the audio routines, under 1 % of their instructions; an opt-in variant until a cycle measurement says more |

Other recompilers' published optimizations, and which applied here, are surveyed in [RECOMP_OPTIMIZATION_SURVEY.md](https://github.com/arcanite24/pinyon-shift/blob/dev/docs/RECOMP_OPTIMIZATION_SURVEY.md).

## Keep the record

Every finding about the game (a function's purpose, a structure offset, a setting's effect, an address in the title update) goes into the repository in the same change: semantic names in `config/mod/fh1-symbols.toml`, everything else as a record in `site/findings/`, which the [Reverse engineering](reverse-engineering.md) pages render, with how it was established and a confidence. Negative results count. The record holds analysis only, never disassembly, decompiled code or game data ([Legal](legal.md)).
