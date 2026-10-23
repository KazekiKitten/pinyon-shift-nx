# Native renderer

Status: direction set 2026-10-21, after the latest Switch race logs. The
renderer is being moved from "make the Xbox 360 GPU emulation fast" to the
method used by `../nfsmw-nx/docs/native-renderer.md`: keep the game's Direct3D
and read the commands it writes, but draw the frame with Vulkan directly.

This document is the FH1 plan. It records what is already native, what is still
Xenia, the evidence from the latest run, and the order of work.

## 1. Why the emulation path is being abandoned

The Switch cannot afford the generic Xenia GPU path for this game. Measured on
the console from the latest race logs (`logs/fh1_006.1.log`,
`logs/rex/rex_perfil.log`):

| Measurement | Value |
| --- | --- |
| Race, CPU 2397 MHz / GPU 1305.6 MHz | 2.0-2.5 fps |
| Race, CPU 1020 MHz / GPU 460.8 MHz | 1.0-1.9 fps |
| Race, CPU 1020 MHz / GPU 1152 MHz (OC, stack run) | 1.5-2.4 fps, CPU 307% |
| Movie, CPU 1020 MHz / GPU 1152 MHz (OC) | 8.3-8.5 fps |
| FMOD audio mixer thread (stack run) | 78.3% of one core |
| Simulation thread (`8255AE10`) | 44.6% |
| `GPU Commands` thread | 40.9% |
| Guest render thread (`825A6320`) | 40.1% (about a third of it waiting) |
| Other guest thread | 38.6% |
| XMA decoder | 15.0% |
| Draws per frame | 1,818-2,596 |
| Draw CPU, normal | 24-39 us/draw |
| Draw CPU, spikes | 116 us/draw |
| CPU by stage | shaders 4-9, textures 2-6, targets 2.1, pipeline 1.1, bindings 3.5, vfetch 3-5, draw 7-14 us |
| Native executor GPU time | 129.6-334.0 ms/frame |
| - transfers | 62.4-140.2 ms |
| - resolves | 44.4-95.8 ms |
| Stack samples in the stack run | ~9,840 per 10 s (`Muestreo de pilas: activo (1 ms)`) |

The stack run changed the picture. The audio mixer thread is the single largest
CPU consumer: FMOD ParamEQ (`sub_82FC6CC0`, reached through the thunk
`sub_82FC7A00`) alone is 11.4% of that thread's samples, reverb
(`sub_8300D580`) 6.2%, the channel matrix mix 2.3%+1.4%, and the DSP arithmetic
around them covers most of the rest. The render thread is flat: no single guest
function dominates, and about a third of its samples are waits. Earlier
"guest render thread 93.1%" readings were the mixer thread under another name.

The picture is the same as in the NFSMW first build: removing GPU work alone
would not reach the target, because the guest render thread and the CPU cost of
imitating the GPU dominate. The latest run spent about 0.93 of a core in the
guest render thread and about 0.20 of a core in `GPU Commands`; the native
executor still cost 130-334 ms of GPU time per frame.

The target is 30 fps. Every optimisation below is judged by frame time and by
whether it removes a per-draw CPU cost, not by how much faster the Xenia path
looks in isolation.

## 2. What is already native, and what is not

FH1 is not starting from zero. `port/switch/sdk/src/graphics/vulkan/fh1_native_executor.cpp`
already owns the render-target side of the frame:

- guest render targets become Vulkan images;
- EDRAM tile transfers become copies or conversion passes;
- resolves write to guest memory and to textures;
- clears are folded into the target;
- draws with no target or no effect are skipped.

The draws themselves still run through Xenia's `IssueDraw`: shader lookup,
texture fetching, pipeline lookup, vertex fetch, binding and recording. That is
the 24-39 us/draw in the table and the part this document replaces.

| Piece | Current state |
| --- | --- |
| PM4 ring reading and GPU state | Xenia-based, working |
| Native render targets and resolves | `fh1_native_executor.cpp`, working |
| Native draw description and recording | missing; Xenia `IssueDraw` |
| Three frame slots | missing; one deferred command buffer |
| Vertex copy thread and upload dedupe | missing |
| Texture fingerprints and interval checks | Xenia texture cache, not NFSMW-style |
| Pipeline cache | present; saved-list prewarm not confirmed |
| Guest native functions | DNET, SleepEx idle, gamma, and the FMOD ParamEQ twin (`fh1_fmod_native.cpp`, off by default) |
| Stack sampling | working; last race run profiled at 1 ms |
| deko3d backend | not started |

## 3. How the native renderer works

The model is the NFSMW document, adapted to FH1:

- The game still believes it is talking to an Xbox 360 GPU.
- The port reads what the game's Direct3D writes: the PM4 ring with settings,
  draws, copies and the Swap that ends a frame.
- The port does not imitate the EDRAM or the Xbox 360 shader pipeline.
- A few hooks on the guest thread add what the command list does not say:
  which shader is which, and which draw call produced which state.
- The frame is recorded with Vulkan and presented through ReXGlue's presenter.

### Threads

| Thread | Role |
| --- | --- |
| Guest threads | Run the game and its Direct3D; write the command list |
| Ring thread | Reads commands, tracks GPU state, records Vulkan |
| Vertex copy thread | Copies vertex and index data into the upload buffer, byte-swapping |
| Presentation | Composes and shows the frame |

### One frame

- Three work slots, each with its own command buffers, fence, upload buffer and
  read-back buffers, so recording the next frame overlaps the GPU drawing the
  current one.
- Render targets are images; resolves are copies or direct writes. A copy is
  skipped when the next use clears the target ("resolve without copy").
- Only the small images the game reads back on the CPU are written back, in the
  exact guest format.
- Presentation uses the presenter's immediate mode.

### Each draw

1. Read the draw settings from the port's copy of the GPU state.
2. Find the pipeline from shaders, settings and constants.
3. Find the textures in a two-level cache.
4. Copy vertices and indices into the upload buffer without duplicates.
5. Write changed shader constants through a dynamic uniform buffer.
6. Bind only what changed and record the draw.

### Lessons carried over

- Fingerprint textures over their raw guest bytes; re-untile only when the
  fingerprint changes, and check less often over time (down to once every 32
  frames).
- Structures that are hashed or compared byte by byte must have no padding;
  every such key gets `static_assert(std::has_unique_object_representations_v<T>)`.
- In busy copy loops, read counts and pointers into local variables first.
- Time only a sample of packets and draws.
- Counters touched by one thread must not be atomic: the Cortex-A57 has no fast
  atomics, and a fetch-add loop both costs and disturbs other cores. This is why
  the D3D census is a one-off probe, not a permanent path.
- Recognise a draw, shader or pass by its signature in three stages: watch,
  apply after a clean run, and switch off for the session on the first known
  failure. The worst case is "does nothing", not a broken frame.
- Native guest functions must be verified against the original. FH1's code was
  compiled with FMA, so expressions have to be written in the same shape and
  order; only registers read later need to match.

## 4. Work order

The order follows the evidence, not the easiest patch.

### Step 0 - measure the guest thread (done, 2026-10-21)

The run succeeded: `switch_stack_profile = true` in the TOML, sampling at 1 ms,
~9,840 samples per 10 s. `port/switch/tools/switch/simbolizar_pilas.py` resolved
the stacks. The result is in the table above.

- `fh1_d3d_census` and `fh1_draw_cpu_profile` were off as intended.
- The audio mixer thread, not the render thread, is the hottest thread and has
  the most concentrated hot functions.

Gate met: a named list of functions with measured shares.

### Step 0.5 - crash from the invalid-fetch flag (fixed)

`gpu_allow_invalid_fetch_constants = true` removed every
`PM4_DRAW_INDX ... Failed in backend` and invalid vertex-fetch message, but a
draw with an unusable shader later reached `ParsedTextureFetchInstruction::
Disassemble` with a null `opcode_name`; `StringBuffer::Append(const char*)`
called `strlen(nullptr)`. `Append` now ignores null, and the disassembler
prints `<null>`. `XamXStudioRequest` and the `nvkmd ... native submission
pressure` warning (NVK recovering from a ~1,990-entry submission, not fatal)
are handled separately.

### Step 1 - native guest functions

Port the hottest functions to C++ with the NFSMW verify guard: compare against
the original for the first 50,000-200,000 calls, then one in 4,096; use the
original result; disable the native version for the session on the first
difference.

The stacks put audio first:

- FMOD ParamEQ (`sub_82FC6CC0` through `sub_82FC7A00`): the first twin, in
  `port/switch/app/src/fh1_fmod_native.cpp`, behind `fh1_fmod_native_parameq`
  (default off until measured). It is the same biquad as
  `pinyon-shift/src/guest_native/fmod_dsp.cpp`, which took 5.7% off the mixer
  thread on the Odin.
- FMOD reverb (`sub_8300D580`) and the channel matrix mix (`sub_82FAE0B8`,
  `sub_82FAB740`) after ParamEQ is measured.

On the render side the stacks are flat, so there is no single guest function to
port; that side waits for Step 2.

Gate: each function shows its own CPU reduction and produces no `DIFERENCIA`.

### Step 2 - native draw description

Describe a draw on the guest thread from the D3D device state, hand it to the
ring thread with a marker, and record it without Xenia's per-draw state
derivation. Start with one self-contained pass (HUD or a scenery list), verify
against the packet path, then expand.

Gate: draw CPU per frame falls on the chosen pass, captures match, and no
uncovered packets.

### Step 3 - frame pipeline

Three slots, a vertex copy thread, upload dedupe, and texture fingerprints.
These hide recording behind the GPU and remove repeated upload work.

Gate: frame time falls without an increase in GPU ms/frame; no read-back race.

### Step 4 - GPU side

Resolve without copy, texture cache eviction, pipeline prewarm, query-pool
resets only for the pools the frame uses, and the streaming read cache.

Gate: GPU ms/frame and transfer/resolve time fall; captures stay within A/A.

### Not in scope yet

- Replacing the game's Direct3D. FH1's textures carry their D3D descriptions in
  game data and `SetTexture` writes fetch constants directly, so the NFSMW
  document's reasons for keeping D3D apply here too.
- deko3d. NVK is the backend until the native path is stable.

### Movie playback (observed 2026-10-21)

Cutscene movies are a separate path from the renderer:

- Base clocks: about 3 fps.
- With GPU overclocking: about 8 fps.
- Changing the CPU clock made no visible difference.

The 2026-10-21 run measured the movie at CPU 1020 MHz / GPU 1152 MHz:
8.3-8.5 fps, 63 draws/frame, `GPU Commands` 11.7% and a native executor GPU
frame of 116-119 ms. The movie is GPU-bound, not guest-CPU-bound, and it is not
fixed by the native draw work. The race in the same run was 1.2-2.0 fps with a
native executor GPU frame of 224.7 ms, so the race is still guest-CPU-bound.

### Correctness fixes in the current build

- `gpu_allow_invalid_fetch_constants = true`: FH1 leaves vertex fetch constant
  90 as the invalid type on a group of small draws. Xenia rejected each draw,
  which produced the `PM4_DRAW_INDX(...): Failed in backend` errors. The flag
  lets those draws proceed with the empty buffer instead of dropping them.
- `XamXStudioRequest` is now a silent raw hook rather than a logged stub; it is
  called repeatedly during movie playback.
- The `nvkmd-switch ... native submission pressure` warnings are NVK recovering
  from a single ~2,000-entry submission by waiting for the oldest accepted
  frame. They are not fatal. Splitting the frame submission is deferred to the
  native draw path.

## 5. Evidence and tools

- Race logs: `logs/fh1_006.1.log`, `logs/fh1_006.log`,
  `logs/rex/rex_perfil.log`.
- Stack symbolizer:
  `port/switch/tools/switch/simbolizar_pilas.py`.
- FH1 native executor:
  `port/switch/sdk/src/graphics/vulkan/fh1_native_executor.cpp`.
- Generic draw path being replaced:
  `port/switch/sdk/src/graphics/vulkan/command_processor.cpp` (`IssueDraw`).
- Method reference: `../nfsmw-nx/docs/native-renderer.md`.
- FH1 D3D research: `../pinyon-shift/docs/D3D_RENDERER_RESEARCH.md`.

## 6. Reporting rule

Every step records the command, the build hash, the measured frame time and the
correctness check. A step that only makes the Xenia path faster does not count
toward the native-renderer goal.
