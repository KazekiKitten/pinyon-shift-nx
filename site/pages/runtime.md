---
title: Runtime and hooks
section: Internals
order: 3
description: Guest memory, the kernel, threads, waits, files and audio in ShiftGlue's runtime, and how Pinyon Shift hooks the game to add host features and run it above 30 fps.
---

# Runtime and hooks

The translated code expects an Xbox 360 around it: a 4 GB address space, the `xboxkrnl` and `xam` kernel exports, six hardware threads, a DVD drive, XMA audio and the Xenos GPU. ShiftGlue's runtime provides each of these on the host. Much of it derives from Xenia; this page covers how it is arranged and what had to change for this game.

## Guest memory

{{diagram:guest-memory-map|The guest address space. The three physical ranges are views of one 512 MB heap with different page sizes.}}

One file-backed mapping of 4.5 GB holds the 4 GB virtual view and the 512 MB physical heap. The physical heap appears three times, at `0xA0000000`, `0xC0000000` and `0xE0000000`, as the console's address decoding does. There is no TLB emulation: a guest address plus the base pointer is the host address.

The `0xE0000000` view starts 4 KB into the physical heap. Windows' classic `MapViewOfFileEx` can only place a view at a 64 KB file offset, so until October 2026 that view was mapped 4 KB short and every generated access at or above `0xE0000000` added `0x1000` back: a compare, a conditional set and a shift on 70 % of the game's memory accesses, about 14 % of all generated host instructions. The runtime now reserves each view as a placeholder (`VirtualAlloc2`) and maps it with `MapViewOfFile3`, which accepts any page-aligned offset, so on Windows a guest access is `base + address` and nothing else; a Windows older than 10 version 1803, which lacks those functions, is refused at start. x86-64 Linux kernels always use 4 KB pages, so the Linux and Android builds assume 4 KB too (`PINYON_SHIFT_PHYSICAL_HEAP_4K_PAGES`, on by default) and refuse to start on a 16 KB-page kernel, where a build with the option off reads the offset at run time as before. Apple silicon (16 KB pages) keeps the `0x1000` add.

Writes to memory the GPU has cached are found with page protection: about 60–70 protect calls covering 830 pages per race frame. On hosts with 16 KB pages, one host page holds four guest pages, so its protection must be the union of the four; taking the first guest page's protection made a committed page next to an uncommitted one fault on macOS.

## Kernel

The runtime implements the exports the game uses and stubs the rest:

| Module | Implemented | Stubbed |
| --- | ---: | ---: |
| `xboxkrnl` | 261 | 616 |
| `xam` | 181 | 1,530 |
| `xbdm` | 0 | 255 |

Implementations include threads, events, semaphores, timers, the file system, content and profiles, and the XAudio render client.

## Threads

Each guest thread is one host thread, named `Guest <start address>`. About 42 are alive in a race; the busy ones are the simulation and render threads, the audio thread and 11 job workers. Guest CPU numbers rotate over six virtual hardware threads, and guest affinities are ignored by default: honouring them, with one host core per Xenon hardware thread, gave no consistent gain.

**The global critical region.** The console disables interrupts for short sections; the runtime turns that into one process-wide recursive mutex, also taken for every guest event and wait (for the handle lookup) and by the vblank interrupt. On the desktop it is contended about 260 times a frame and blocks for about 0.34 ms of a race frame, so it was left alone there. On Android it caused visible hitches ([#416](https://github.com/arcanite24/pinyon-shift/issues/416)): a hold log (`critical_region_hold_log_ms`) and a watchdog that names the holder, matched with `simpleperf`, showed file system path lookups and AAudio stream opens running under the lock, blocking the game's thread for up to 39 ms behind I/O.

| Long drive, Odin, warm | Before | After |
| --- | ---: | ---: |
| Frames over 17.5 ms | 2.3 % | 1.2–1.3 % |
| Worst frame | 186 ms | 45–48 ms |
| Lock wait, p99 | 39 ms | 8–9 ms |

The fixes moved file lookups and audio opens off the lock, reused stored pipelines, kept one readback buffer and allocated texture memory at start. Single `mprotect` calls of 6–12 ms under the lock remain, with about 5,000 mappings in the process.

## Waits and clocks

Small changes in how the host waits paid off more than most code generation work:

| Change | Measured |
| --- | --- |
| The game polled GPU fences in a loop; a hook now spins 20 µs, then blocks on the GPU's write signal for at most 1 ms | process CPU −15 % (186 to 159 s per run) |
| Lock-free guest clock reads; the timer queue thread blocks while empty instead of yield-spinning | process CPU 155 to 146 s; timer thread 4 to 0.4 s; vsync thread 1.4 to 0.03 s |
| Critical sections read before each compare-exchange and stop after 1,024 tries, not up to 65,280 | |
| The render thread's idle `SleepEx(0, TRUE)` spin became a 200 µs sleep | Odin render thread 477–839 to 242–253 ms of CPU a second, p99 frame 38–40 to 33.6 ms; desktop p99 18.5 to 16.9 ms |
| POSIX multi-object and alertable waits wake on signal instead of polling every 1 ms | Odin process CPU −6 to −9 %, audio thread −9 to −12 % |
| Vblank timing with high-resolution waitable timers and a spin tail | vblank lateness 43 µs mean |

Two host behaviours to watch for: Windows rounds a sub-millisecond `Sleep` to a yield, and a yield that returns at once can expose races the console's scheduler hid. The game's job producer gave up after 1,000 `NtYieldExecution` calls on Android; a hook now waits in host time there.

## Files, content and audio

- **File system.** Host path devices mount the extracted disc as `game:` and `d:`, the title update as `update:`, and a writable `cache:`. Lookups are case-insensitive. The tree has its own lock (the #416 fix).
- **DLC.** STFS packages mount through a container device, with the license mask read from the package header. The game's marketplace mount appears as `DLCRoot<n>`.
- **Mods.** An overlay device layers mod files over the disc's, so a mod never edits game files.
- **Audio.** XMA is decoded with FFmpeg's `xmaframes` decoder. ShiftGlue added packet handles across buffers and assembly of frames split over up to four packets, ported from Xenia Canary. Output goes through SDL3, or AAudio on Android.
- **Input.** SDL3 gamepads, XInput, and mouse and keyboard.
- **Saves.** Raw files under a fixed profile, written atomically and backed up after each write.

## Hooks

Host code reaches into the game in three ways, all declared in configuration or source and all applied at code generation time. Guest memory is never patched while the game runs.

{{diagram:midasm-hook|A mid-asm hook is a direct call inserted into the generated function at a guest address.}}

**Mid-asm hooks.** A `[[midasm_hook]]` entry in the analysis TOML names a guest address, a host function and the registers it receives, or the whole context. The generator inserts a direct call at that point. Variants return from the guest function or jump to another address when the host function returns true or false. The base image has 130. Examples:

- The pause menu's MULTIPLAYER entry opens the host settings instead.
- The title's unchanged gamma ramp is skipped; it had been 17 % and 13 % of the render thread.
- The fence poll loop blocks on the GPU instead of spinning.
- Xenia Canary's patch file for this game is reproduced as setting-gated hooks that skip or replace instructions, such as the motion blur and depth of field switches.

**Whole-function replacement.** Defining the same `sub_` symbol in `src/guest_native/` replaces a generated function. Each replacement hashes the guest code it replaces before first use, has its own setting, and can check every Nth call against the original. The CRT's `memcpy`, `memmove` and `memset` run as host code this way; with atomic `stwcx.`, that cut 11–14 % of the simulation thread's cycles. Native `pow` and the LZX decoder are bit-identical over 10.9 million and 17,535 calls and about twice as fast.

**Symbols.** Addresses and structure offsets that host code and mods use have names in `config/mod/fh1-symbols.toml`. A generator merges them with every hook site into a header, and a test fails when the two disagree. Native mods look up symbols by name and never use literal addresses.

## Above 30 fps

The console runs the game at 30 fps. Here it runs at 30, 40, 60 or 120 at the same game speed.

The game waits for two vblanks per frame and steps its simulation once per two vblanks, so the runtime runs the guest vblank at twice the chosen limit. The old 60 fps cap was simply the vblank. Gameplay integrates a delta from a millisecond clock, so driving, physics and the clock run at the right speed at any rate; an optional host clock delta, capped at two ticks, is available behind settings.

A few systems added a constant step per update instead. They were found by comparing guest memory snapshots taken at 30 and 120 fps (`tools/scan-guest-snapshots.py`), then trapping page writes to find the code that changed the value:

| System | Was | Now |
| --- | --- | --- |
| Purchase and reveal cameras | 1/30 s per update | real elapsed time |
| Trackside crowd animation | one frame per rendered frame | whole 30 Hz steps of real time, fraction carried over |

Over 60 rendered frames the crowd now advances 16 animation frames at 120 fps and 60 at 30 fps; before, it advanced 60 at both. The showroom orbit, a model presentation and the radio popup timer have the same pattern and are not hooked yet.

Gates for any change in this area: simulation time within 0.95–1.08 of real time over a scripted route, pose drift, and a hash of the save it writes.
