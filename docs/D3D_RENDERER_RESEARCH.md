# D3D-level renderer research

Status: research done 2026-10-14. DL-0.1 (census) passed, DL-0.2 found the
recording brackets, DL-0.3 was rejected; DL-1.1 landed on its gate (ceiling
about 3 ms a frame net on the Odin), so whether to go on is open.

The near-native plan ([NEAR_NATIVE_RESEARCH.md](NEAR_NATIVE_RESEARCH.md))
ended with the GPU front end as the largest pool left on the Odin: the guest
builds Xenos command buffers, the host decodes them (about 9 ms a frame),
submits (2.7 ms) and records. Every attempt to make that layer cheaper from
the inside failed (G0, NN-2.2, NN-2.6). This page asks whether to replace
the layer: take the game at its Direct3D calls and drive Vulkan from them,
instead of emulating the GPU at the PM4 packet level.

Item prefix: DL-. Detailed notes, with addresses and run folders, are in
`.local/backlog-research/d3d-renderer-2026-10-14/` (01 prior work and
architecture, 02 the guest D3D seam, 03 prior art, 04 cost ceiling and
gates). Reverse-engineering results are recorded in
`site/findings/rendering.toml`, group "D3D inside the game".

## Answer in short

- **A pure draw-call renderer does not fit FH1.** Most of the scene does
  not go through draw calls. It arrives as prebuilt D3D command buffers
  (display lists, PM4 inside), some streamed in from asset files and some
  recorded by the track ahead of time. This is why the project's earlier
  native renderer moved to decoded PM4, and why NEAR_NATIVE rejected
  "D3D draw-call HLE only (UnleashedRecomp's route)".
- **A hybrid could fit:** draw calls taken at the engine's own device class,
  plus a **list compiler** that translates each display list once and
  replays the translation, keyed on the list and its *fixups*. New in this
  research: the lists are not re-recorded every frame. D3D patches
  per-object textures, streams and constants into fixed slots before each
  run. That explains why NN-0.10 found lists both repeating byte for byte
  and being rewritten. It also means a compiler keyed on (list, fixup
  values) need not hash bytes, which is what made G0 and the recorder
  replays slower.
- **Ceiling on the Odin: about 2-5 ms of CPU a frame realistically**, 6-9.5
  ms at best, nothing at worst, out of about 13.7 ms on the GPU path today.
  The deciding unknown is the **fallback share**: draws whose bytes reach
  the GPU through a path the renderer cannot see, which would still need
  the PM4 decoder. GPU time saves only 0.2-0.6 ms, so the GPU cannot justify
  the project. Desktop would save an estimated 4-8 ms and the Deck 7-15 ms,
  where it would show as power, since the Deck is GPU and power bound.
- **The closest precedent is CoD3Recomp** (a ReXGlue port of Call of Duty 3).
  It records command buffers on four threads, replays them under predicated
  tiling and copies its own pre-built state packets into them, much as FH1
  does. It keeps a small non-executing packet reader at record time and
  doubled its frame rate in one scene.
- **DL-0.1 passed (2026-10-14):** 9.5-16 % of drawn draws would need the
  fallback on the Odin and 5-16 % on the desktop, and the visible draws
  carry about 10 ms of decoder and submission time a frame.
- **DL-1.1 is at its gate, not past it (2026-10-14):** with the PM4 path
  doing no work for the visible draws, Odin process CPU fell 6.28 ± 0.42 ms
  against a 6.17 ms gate, about 3 ms a frame net of the native draw cost.
  That is the ceiling of the whole renderer on the Odin, before fidelity.
- **Original recommendation: run DL-0.1, the source census, before any design work.**
  It is a probe build of default-off hooks. Go only if the fallback share is
  30 % or less and the draws a hybrid can see carry at least 6 ms of
  decoder and submission time a frame.

## What is native today and what is still Xenos

The renderer is already "native" in places. The FH1 native executor owns
EDRAM, clears, resolves, the swap and the guest-visible side effects. Still
Xenos emulation:

- the PM4 decode;
- the register file;
- deriving each draw's state from registers (about 20 steps, about 980 ns a
  draw on desktop);
- the 512 MB guest-memory mirror;
- the tiled texture cache;
- a shader ABI that reads Xenos registers.

On Vulkan the old render-target cache is still built as a fallback.

Attempts to reuse repeated work at this layer all measured slower or below
their bars:

| Attempt | Result |
| --- | --- |
| Per-draw templates | 1,205 against 1,115 ns a draw |
| Buffer replay | 1,571 against 1,472 ns a draw |
| Segment replay | recorder 0.3 % faster |
| Constants by address (NL-3.3) | recorder 7.85-8.49 against 7.47-7.72 ms |
| Native draw ABI (NP-9.5) | about a sixth of one thread at most, not built |
| G0 replay probe (NN-0.10) | -2.54 ms of process CPU against a 6 ms bar |

The common cause: checking that a draw is still valid cost about as much as
deriving it, and nearly every draw brings new shader constants. A D3D-level
renderer avoids the check only where the API says what changed. That is
true for draw calls and for list fixups, and false for list bytes written
any other way.

What a D3D-level renderer must still provide to the game:

- the fence words the title polls, the InsertCallback wait and interrupt
  handshake (about 12 waits a frame), vblank and the ring read pointer;
- the car thumbnail and other resolves the CPU reads;
- the resolve chains the HDR image depends on;
- EDRAM aliasing between formats;
- per-band culling under tiling;
- about 20 MB of CPU-written vertex and index data a frame;
- occlusion queries while loading.

The game never uses memory export.

Reusable as they are:

- the shader translator and shader packs;
- texture decode;
- the pipeline cache;
- the executor's surface and resolve code;
- the presenter;
- the render-test tooling.

## How FH1 reaches the GPU

Details and addresses: findings "engine graphics device class", "D3D
command-buffer fixups", "command buffers from assets and run-time
recording", "D3D command buffers", "D3D draw entry points".

- D3D9 from XDK 2.0.21119 is linked into the executable, in two code bands.
  72 functions write PM4 headers, all D3D. The engine itself writes no PM4
  and no GPU register.
- **The engine draws through its own virtual class `CD3D9GraphicsDevice`**
  (67 slots). Its draw slots reach every known D3D draw entry point, so one
  vtable hook sees every immediate draw, with the state calls before it.
  Most D3D state setters are inlined into the engine as stores plus dirty
  bits, so there is no SetRenderState function to hook below this class.
- **Display lists** run through `D3DDevice_RunCommandBuffer` (542 a
  presented frame). Before each run the owner applies the object's dynamic
  fixups through D3D's fixup dispatcher, one setter per resource type.
- **Origins:** lists come from asset files (models, with static and dynamic
  fixup tables), from run-time recording (track zones, within a time and
  fixup budget), and possibly from cloning.
- **Tiling:** D3D's worker replays the tiling stream once per tile. At the
  API level each logical draw is seen once, with its bin mask, and the
  renderer must apply the game's per-band culling itself.

**Coverage, as an estimate.** About 610 immediate draw calls and 542 list
runs per presented frame (desktop probe, route average). Drawn race draws
are estimated at 55-65 % from lists and 35-45 % from immediate calls
(bounds 40 % and 75 % for lists). The swing depends on whether the two main
draw entry points (`82416380`, `82415F68`, about 540 calls a frame) write
into ring segments or into lists being recorded. The earlier "42 draws a
frame through D3D" count covered only the `8240F4D8` wrapper, so the two
numbers do not conflict.

## Prior art

| Project | Layer intercepted | How it handles the hard parts | Result |
| --- | --- | --- | --- |
| Unleashed Recompiled (Sonic Unleashed, 360) | D3D device replaced, about 40 functions; inlined setters caught by the device layout and dirty flags | no EDRAM model, no tiling; resolves alias the render target until a copy is needed | no published performance numbers |
| Marathon Recompiled (Sonic 06) | Unleashed's renderer | tiling forced off by making the game's surface-size check return 0 | FH1's own non-tiled path drops the static world, so this does not carry over |
| CoD3Recomp (ReXGlue) | D3D device, plus a non-executing reader for the packets the game copies into its lists | lists recorded on four threads, replayed per predication mask | 0 mismatches in about 390,000 draws per 5 s; 91 to 182 fps in one scene |
| Deadly Premonition (ReXGlue) | D3D device; command stream dropped unparsed | EDRAM aliasing added back by hand; most bugs in the shader translator | 5.1-6.1 ms CPU a frame at 60 fps (RTX 5070, 2x) |
| Downpour attempt (ReXGlue) | above the device layer, then a hybrid over the emulated GPU | missed draws; buffers freed while in use | abandoned as a dead end |
| Cxbx-Reloaded (original Xbox) | D3D8 patches, plus a push-buffer interpreter for games that run push buffers | had to add the interpreter | 16 % of 1,032 titles playable |
| Xenia, RPCS3, Dolphin | hardware commands | the D3D library is compiled into each 360 game, so there is no shared API | |

Failure modes others reported:

- hooking above the device layer;
- trusting device state the game overwrites with its own packets;
- dropping EDRAM aliasing;
- shader translation bugs;
- drawing on top of the emulated GPU;
- freeing buffers queued work still uses;
- hook cost while off (measure p90 and p99, not the median);
- per-game effort: none of these renderers is reusable across games.

## Cost ceiling (Odin race, base build, rows 4300-6900, about 1,890 drawn draws a frame)

| Part | ms a frame | M instructions a frame |
| --- | ---: | ---: |
| PM4 decoder thread (decodes and records Vulkan inline) | 7.3-9.9 | 42-63 |
| GPU submission thread | 2.6-3.0 | 6-8 |
| Guest render thread | 4.3-4.9 | 11-14 |
| of which guest D3D code (estimate, with two helper threads) | 0.8-0.9 | |
| Write-watch protects and faults | about 0.5 | |
| Everything else | 17-21 | |

Inside the decoder, the per-draw work is 4.1-4.8 ms (constants about 1.4),
PM4 parsing about 2.7 ms and shader-hash reloads about 0.9 ms.

A D3D-level renderer:

- **Removes:** PM4 parsing for the draws it sees, the Xenos-specific state
  derivation (an estimated 1.4-1.9 ms), the tile replays and most of the
  write-watch work. The shader rehash can be fixed on its own, without this
  project (DL-0.3).
- **Keeps:** about 60 % of today's per-draw cost (pipelines, constants,
  descriptors and the draw itself, about 1.6-1.8 µs a drawn draw) and the
  driver's command emission on the submission thread (2.0-2.8 ms).
- **Adds:** state capture on the render thread, which roughly cancels the
  guest D3D code it replaces, and the fixed cost of a PM4 fallback.

| Fallback share | Odin CPU saved a frame (estimate) |
| --- | --- |
| 10 % or less | 6-9.5 ms (best case) |
| 30-60 % | 2-5 ms (realistic) |
| over 70 % | nothing, or a loss |

A cross-check against G0's measured replay agrees: about 4.1-4.9 µs net
per converted draw.

## Design if the gates pass

- **Seam:** the `CD3D9GraphicsDevice` vtable for immediate draws, state,
  resources, resolves and present. `RunCommandBuffer`, the fixup
  dispatchers and the list loaders for display lists.
- **List compiler:** translate a list's PM4 once, when it is loaded or
  recorded, into host draws with its fixup slots as host bindings. Replay
  the translation at each run with the caller's inherited state. Key it on
  the list and its fixups; any other write to a list invalidates the
  translation.
- **Packet reader:** a CoD3-style reader at record time, which executes
  nothing, for the state packets the game copies into lists.
- **Tiling:** replay each logical draw once per band with that band's
  scissor and the game's per-band culling. There is no 10 MB EDRAM limit on
  the host, so the render target is full size.
- **Kept:** shader translation, texture decode, the executor's surfaces,
  resolves and presenter, and the guest-visible fence and interrupt
  protocol.
- **Fallback:** draws from a path the renderer cannot see keep the PM4
  decoder, with an explicit count. A hybrid drawing on top of the emulated
  GPU was a dead end for Downpour, so the fallback must hand whole passes or
  frames to the decoder, not single draws.

LEGAL.md allows this: it is interface-level host code written from our own
analysis, and the shader translation stays generated.

## Items

| Item | What | Gate | Size |
| --- | --- | --- | --- |
| DL-0.1 | **Source census** (probe build, default-off hooks, no behaviour change). Entry hooks on the draw entry points log whether the device writes into the ring, a list being recorded or the tiling stream. Count calls per vtable slot. Trace each list's life through RunCommandBuffer, the fixup dispatchers, the file loader and the clone path. Classify every write into a list as fixup, stream load, clone or other. In the decoder, tag every drawn draw by the class of its bytes, and time the decoder and the guest D3D functions by class. Routes: race (tiled desktop, untiled Odin), map, car select. | Go if "other" writes to lists are 0, the fallback share is 30 % or less, and the visible draws carry at least 6 ms of decoder plus submission time on the Odin. 30-50 % fallback: only with the list compiler. No-go above 50 % or under 4 ms. | S-M |
| DL-0.2 | **Find the recording brackets**: BeginCommandBuffer, EndCommandBuffer and BeginTiling, by watching the device's write pointer for one frame. The async command-buffer path (`829EC928`): how many lists it runs and where it fixes them up. | Needed for DL-0.1's attribution | S |
| DL-0.3 | **Shader-hash reload fix** inside today's decoder (about 0.9 ms a frame), independent of the rest | in-run A/B, decoder CPU -0.5 ms | S |
| DL-1.1 | **Wrong-image ceiling**: skip decode and recording for the draws DL-0.1 marks visible, toggled in-run | process CPU drop of at least (visible draws × 2.2 µs) + 3 ms, about -6 to -7 ms | S |
| DL-1.2 | **Fidelity pilot**: the HUD pass (about 42 draws, about 0.2 ms) through the new path, against captures. Below noise as a cost gate. | captures within A/A; no frame-time tail change | M |
| DL-2.1 | **First native slice**: immediate draws of one self-contained pass (car or vegetation lists), with the list compiler for its lists | at least -3 ms in-run on three pooled runs; decoder instructions per draw -30 %; p99 no worse; captures within A/A | L |
| DL-2.2 | **Tiling at the API level** for that slice: replay per band with the game's per-band culling | same captures, untile counters at 0 for the slice | M |
| DL-3 | **Whole frame**: every pass, the PM4 decoder kept only as an explicit fallback | DL-2's gates on the whole race, the Deck and desktop; GPU wins count only if KGSL busy falls by 2 SE pooled | XL |

## Measurement method

As NEAR_NATIVE:

- CPU results are judged in-run only: drawn draws swing 753-1,859 between
  runs, which moves raw instructions by 20 %.
- In-run window means are adjusted for draw count: the toggles fall on the
  same route frames in every run, so one side can carry a heavier scene
  phase (DL-0.3 saw 170-590 more draws in every memo-on window). An A/A on
  the same route shows the bias.
- One in-run A/B resolves about ±0.9 ms.
- Cross-build per-thread instructions spread 1.1-4.9 %.
- p90 and p99 frame times are checked as well as means.
- Device runs use private state roots and pinned seeds.

## Risks and open questions

- The fallback share is unknown until DL-0.1. If `82416380` and `82415F68`
  record into lists every frame, a record-time translation pays every frame
  too, and the project shrinks toward NN-2.3.
- The resource-type numbering of the fixup dispatcher is assumed from the
  XDK and is checked only for textures and command buffers.
- The v4 image shares the runtime (every seam function maps at a constant
  offset per band, two unverified), but the v4 vtable addresses need the v4
  image.
- Per-game effort is large: no 360 D3D-level renderer is reusable, and each
  project re-found its own addresses.
- Shader translation bugs dominated other projects' visual bugs. Ours is
  mature, but its ABI reads Xenos registers and would need a new constant
  layout.

## Progress

| Item | Outcome | Evidence |
| --- | --- | --- |
| Research | **Done 2026-10-14.** Four research notes, findings recorded ("engine graphics device class", "D3D command-buffer fixups", "command buffers from assets and run-time recording"; corrections to "D3D command buffers" and "display-list writers"). Recommendation: run DL-0.1 before any design work. | `.local/backlog-research/d3d-renderer-2026-10-14/`; `site/findings/rendering.toml` |
| DL-0.1 | **Passed 2026-10-14.** Census probe (`pinyon_shift_d3d_census`, default off; with it off the probe build matched build X at 2.43 against 2.45 µs of decoder time per decoded draw). Odin race, untiled, 600-frame windows: drawn draws from display lists 64.5-77.5 %, immediate calls 20-30 %, one unattributed buffer 72 a frame; **fallback share 9.5-16 %** (the unattributed buffer, plus list draws whose list changed since its previous run). Desktop tiled race: lists 60-83 %, fallback 5-16 %. List runs byte-identical to their previous run: 83-100 %; every changed list was recorded at run time (the track), so it is re-recorded rather than patched in place, and no list run showed only fixup changes. Origins of list draws: loaded and streamed from assets 46-66 %, cloned 18-64 %, recorded 7-17 %. Writes into watched lists: fixups and stream loads only in the plain census; with the watches re-armed, 5-13 "other" writes into known lists per 600-frame window (about 0.01-0.02 a frame), so a list compiler must still invalidate on any write. Time behind the visible draws: 73-99 % of the decoder (census on), about 7-8 ms of the 9.8 ms census-off decoder plus about 2.7 ms of submission, above the 6 ms bar. | `.local/backlog-research/d3d-renderer-2026-10-14/dl01-probe.md`, `desk-cen.state/logs/runtime.log`; Odin runs `stage1/odin/dl01-{off,cen,rearm,brk}` under `.local/backlog-research/near-native-2026-10-13/` |
| DL-0.2 | **Done 2026-10-14.** From the buffer-switch trace of one race frame: `82468C40` is BeginCommandBuffer (it redirects the device's write pointer into the buffer being recorded) and `823EA3E0` EndCommandBuffer, about 3 a frame; `823EB3D0` opens a tiling bracket and `82469290` closes it, once a frame. Recording runs on its own D3D device, and the indexed draw entry point `82416380` writes into the lists being recorded. | `stage1/odin/dl01-brk/runtime.log`; `site/findings/rendering.toml` |
| DL-1.1 | **At the gate 2026-10-14, not a clear pass.** `gpu_d3d_census_skip_visible` (hot, default 0) makes the PM4 path do no work for draws in buffers DL-0.1 counts as visible: mode 1 skips draw packets (state derivation, recording, submission; shader loads deferred to the next executed draw), mode 2 also shader constants, mode 3 also every other register write except the ranges fences, render targets, windows, copies and resolves read. Events, waits, memory writes, interrupts, swaps, queries, nested buffers and EDRAM copies always run (about 34 resolves a frame inside visible buffers still ran); the race finished in the same game state with only the HUD drawn. A lean census mode (`pinyon_shift_d3d_census_lean`, classification only) keeps the race at 60 fps; both sides pay its 2.6 ms of decoder. Odin race, in-run A/B every 180 frames, both orders, regressed on decoded draws: mode 3 (4 runs) process CPU -6.28 ± 0.42 ms against a gate of 6.17 ms (1,441 visible draws × 2.2 µs + 3 ms), per run -6.08, -5.97, -5.96, -7.57 against 6.37, 6.37, 6.25, 5.69; decoder -3.46 ms (11.20 to 7.96, -31 %, short of the 50 % no-go line in note 04), submission -1.57 ms, render thread -0.60 ms. Mode 2: -5.62 ± 0.47 against 6.25; mode 1 (1 run): -4.22 ± 0.89. Net of the native draw cost the ceiling is 3.1 ± 0.4 ms a frame, against the 3 ms bar. The skip still walks every packet of the visible buffers (understates the ceiling by perhaps 1-2 ms) but also drops texture and vertex uploads and write-watch work a native renderer would keep (overstates it by about as much). | `.local/backlog-research/d3d-renderer-2026-10-14/dl11.md`; Odin runs `stage1/odin/dl11-*`, `dl11b-*`, tables `stage1/dl11-mode{2,3}.txt` under `.local/backlog-research/near-native-2026-10-13/` |
| DL-0.3 | **Rejected 2026-10-14.** `gpu_shader_load_memo` keyed the shader by (type, guest address, dword count), each entry held by a one-shot write watch on its microcode. Verify: 0 mismatches in 30.1 M and 27.0 M loads; hit rate 96.2 % (1,024 entries) and 99.77 % (4,096, two-way). Four in-run A/Bs on the Odin race: raw decoder differences were within noise because the memo-on windows decoded 170-590 more draws in every run (the toggles fall on the same route frames, so window means carry the scene phase); adjusted for draws, decoder -0.32 ± 0.09 ms pooled, process -0.05 ± 0.22 ms, frame unchanged, against the -0.5 ms gate. The 0.9 ms estimate was an inclusive profile share. Code reverted; patch kept. | `.local/backlog-research/d3d-renderer-2026-10-14/dl03.md`, `dl03-sdk.patch`; `site/pages/lessons.md` |

## Sources

- [NEAR_NATIVE_RESEARCH.md](NEAR_NATIVE_RESEARCH.md): Where the overhead
  is, NN-0.10 (G0), NN-2.2, NN-2.6, NN-2.7.
- [NATIVE_PORT_BACKLOG.md](NATIVE_PORT_BACKLOG.md) NP-9.5;
  [PERFORMANCE_BACKLOG.md](PERFORMANCE_BACKLOG.md) "What the fast ones do";
  [DESKTOP_RENDERER_BACKLOG.md](DESKTOP_RENDERER_BACKLOG.md);
  [RECORDER_REPLAY_BACKLOG.md](RECORDER_REPLAY_BACKLOG.md).
- `docs/native-renderer/` (RESEARCH.md, XENOS_RETIREMENT_BACKLOG.md,
  GUEST_VISIBLE_RENDER_DEPENDENCIES.md, archive/RENDER_PASS_CENSUS.md).
- Prior-art links are in the 03 note.
