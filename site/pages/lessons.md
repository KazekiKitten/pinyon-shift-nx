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

Most per-draw savings came from noticing that inputs hadn't changed. 58 % of draws changed only shader constants, so caching pipeline, binding and constant derivation behind a state epoch paid off repeatedly. Replaying whole recorded draws did not: proving a recorded draw is still valid cost as much as deriving it.

## Waits are performance

The largest CPU savings outside the renderer came from how the host waits, not from translated code:

- The game's GPU fence poll loop, turned into a short spin and a block: −15 % process CPU.
- A spinning timer thread, a spinning render idle loop and polled multi-waits, each turned into a blocking wait.
- Windows rounds sub-millisecond sleeps to yields; a yield that returns at once can expose a race the console's scheduler hid.

## Let the calling convention bound the state you sync

Keeping guest registers in host locals only pays if the syncs with the register file are cheap. Writing every local back and reloading it around each call cost as much as it saved. The guest ABI already says which state survives a call. On PowerPC that is cr2–cr4 among the condition fields, so a call or return writes back only those and reloads nothing. That turned a measured no-gain into 11–12 % fewer instructions on the hot threads. Keep the full sync only where code reads the register file directly: hooks, `setjmp`/`longjmp` and exceptions. See [Recompiler](recompiler.md#what-the-generator-emits).

The same reasoning applies to tracked modes such as the float flush mode: a small dataflow pass over the generated function, meeting the state of every path into a label, removed 29 % of the toggles.

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
- **Instructions, not CPU time, across builds.** CPU time per guest thread is bimodal between runs of the same build. Retired instructions a second per thread, sampled at a fixed frame-rate limit, separate builds within four runs each.
- **Inclusive profiles from frame pointers.** `simpleperf record --call-graph fp` gives caller totals on Android without a profiling build; about 1 % of chains break. Rank callers this way before porting a leaf.
- **Train and measure PGO on different routes**, so the profile can't fit the measured run.
- **HDR on Android: check the layer, not the screenshot.** Android 13 lists no HDR10 color space to Vulkan even on an HDR10 panel; a 10-bit swapchain with `ANativeWindow_setBuffersDataSpace(ADATASPACE_BT2020_PQ)` gets one. `dumpsys SurfaceFlinger` shows the layer's data space and whether the display entered its HDR mode; `screencap` tone-maps the layer to SDR and makes correct HDR look dark. Read the composer's own table at the end of that dump too: on a panel mounted portrait, a landscape layer goes through an 8-bit rotator and is tone-mapped to SDR before it, so HDR10 only reaches the panel from a swapchain pre-rotated with the surface's `currentTransform`.
- **Check what the pinned host tools link.** LLVM's Linux release builds `ld.lld` against `libxml2.so.2`. libxml2 2.14 renamed it `libxml2.so.16`, so on SteamOS and Arch the linker couldn't start, and every compiler check failed with "unable to execute command". The tools that need it now run through wrappers that load only that library and its ICU from the sysroot. Try a new pin in a current Arch container before release.
- **Fix the order of anything you hash.** The DLC payload digest hashed a sorted file list, and Python sorts paths without case on Windows but with case on macOS and Linux. Rally verified on Windows and failed everywhere else with the same files. The digest now sorts the Windows way on every platform, which keeps the published digests valid.
- **Check that a developer option has a reader before using it.** Retail builds often keep the developer option parser and drop the code that used an option. FH1 parses `eventrestrictions` and `chooseillegalcarforevent`, but none of the 356 callers of the option object's getter reads them. A scan for loads from the getter's result, checked against options known to work, settled this without a run. The trainer patches the game's restriction parser instead.
- **Make the test car fail the limit you test.** The first event the route reached was one the save's car already qualified for, so the stock and the cheated runs looked the same. A database mod that limited that event to 1980s cars made the stock game refuse the car, which is what the cheat then had to change. A second mod that limited the class showed that the class is applied by a different function, which needed a hook of its own.
- **Never quote one GPU's saving for another.** The same switch saved 8 % on one GPU and nothing on the next.

## What didn't pay off here

Negative results, so they aren't retried without a new reason:

| Idea | Result |
| --- | --- |
| CR fields in C++ locals, synced at every call | binaries 13–26 % larger for no gain; syncing by the calling convention instead paid (see above) |
| ThinLTO on the generated code | neutral on guest-thread instructions |
| More CRT functions as native code | the remaining candidates are 0.02 % each in a race |
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

Other recompilers' published optimizations, and which applied here, are surveyed in [RECOMP_OPTIMIZATION_SURVEY.md](https://github.com/arcanite24/pinyon-shift/blob/dev/docs/RECOMP_OPTIMIZATION_SURVEY.md).

## Keep the record

Every finding about the game (a function's purpose, a structure offset, a setting's effect, an address in the title update) goes into the repository in the same change: semantic names in `config/mod/fh1-symbols.toml`, everything else as a row in [REVERSE_ENGINEERING.md](https://github.com/arcanite24/pinyon-shift/blob/dev/docs/REVERSE_ENGINEERING.md) with how it was established and a confidence. Negative results count. The record holds analysis only, never disassembly, decompiled code or game data ([Legal](legal.md)).
