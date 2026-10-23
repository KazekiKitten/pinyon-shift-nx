# PinyonShift-NX — Nintendo Switch port work folder

Working folder for porting the Xbox 360 retail release of *Forza Horizon*
(USA, serial `MS-2505`, title ID `4D5309C9`) to the Nintendo Switch by static
recompilation with ReXGlue, following the method of nfsmw-nx, masseffect-nx
and sa2-nx.

The renderer direction is now the native renderer of `../nfsmw-nx`: keep the
game's Direct3D and read the PM4 commands it writes, but draw with Vulkan
directly instead of making the Xbox 360 GPU emulation fast. The plan, current
state and measurements are in [`docs/NATIVE-RENDERER.md`](docs/NATIVE-RENDERER.md).

This folder holds **no game data, disc images, generated code, extracted
assets or executables**. The user's own ISO stays in `../gamedump/`. This
folder holds only our own notes, decisions, scripts and generated reports.

## Layout

- `docs/` — our analysis and decisions; `NATIVE-RENDERER.md` is the renderer
  direction and work order.
- `analysis/` — raw command output kept as evidence (text only).
- `logs/` — command logs from setup work.
- `switch/` — source, SDK and staged build for the Switch port.
- `switch/tools/switch/simbolizar_pilas.py` — resolves the profiler's
  `imagen+0x...` stack samples against the unstripped ELF.

## Sources (read-only inputs, outside this folder)

| Path | Role |
| --- | --- |
| `../gamedump/*.iso` | The user's own USA retail disc dump |
| `../pinyon-shift` | Existing PC recomp (BSD-3-Clause); manifest, host code, tools |
| `../sdk-pinyon` | Clone of `arcanite24/shiftglue-sdk` at pinyon-shift's pinned commit |
| `../sa2-nx` | Reuse source: Switch SDK fork, tools, renderer |
| `../nfsmw-nx` | Method reference (`docs/native-renderer.md`, `platform-notes.md`, `toolchain.md`, `measuring.md`) |

## Rules carried from the brief and the upstream repos

- Every analysis entry carries its evidence (command and observed result).
- Test runs never take over the desktop: muted, minimised; never truncate the
  boot test's output (no `Select-Object -First`).
- No game data, disc images, generated code, extracted assets or executables in
  any repository. Keep pinyon-shift's repository boundary checks intact.
- The Switch build takes the user's own game files and ships none.
- Keep Microsoft, Turn 10 and Playground Games names and logos out of the
  project name and branding.
- Report results faithfully, including what was not verified.

## Stage plan (one stage at a time, verify before moving on)

1. Baseline: reproduce the PC build, capture reference video, record pins,
   patches and manifest, and decide the SDK merge direction.
   Status: done; see [`docs/STAGE1-BASELINE.md`](docs/STAGE1-BASELINE.md).
2. Re-run the missed-code sweeps on the Forza codegen after every codegen.
   Status: in progress; inventory in
   [`docs/STAGE2-ANALYSIS-CATALOGUE.md`](docs/STAGE2-ANALYSIS-CATALOGUE.md).
3. Platform-independent host layer. Status: working on Switch through ReXGlue.
4. Native renderer. Status: in progress on Switch. The render-target executor
   is native; draws still use Xenia's `IssueDraw`. Next: guest stack profile,
   native guest functions, then the native draw path. See
   [`docs/NATIVE-RENDERER.md`](docs/NATIVE-RENDERER.md).
5. GPU optimisations, then Switch. Status: in progress; transfers and resolves
   are the largest GPU costs in the latest race (62-140 ms and 44-96 ms per
   frame).
6. Switch GPU backend from NVK to deko3d. Status: not started; NVK stays until
   the native draw path is stable.

## Current Switch state

- Latest staged NRO: `fc7f8ea1e66bb6615ec8ffd2c46086961e9a1cdd64fe55de202eeaa568d60c8d`.
- Latest race (stack run, CPU 1020 MHz / GPU 1152 MHz): 1.5-2.4 fps, CPU 307%.
  At CPU 2397 MHz / GPU 1305.6 MHz the race reached 2.0-2.5 fps.
- The FMOD audio mixer thread is the frame limiter (78.3% of one core); the
  render thread (`825A6320`) is 40.1% and its stacks are flat. FMOD ParamEQ
  (`sub_82FC6CC0`) is 11.4% of the mixer alone.
- Stack sampling worked at 1 ms in the stack run; `fh1_d3d_census` and
  `fh1_draw_cpu_profile` were off so the profile stayed clean.
- `gpu_allow_invalid_fetch_constants = true` removed every PM4 backend and
  invalid-fetch error; the null `opcode_name` crash it exposed is fixed.
- A native FMOD ParamEQ twin is built in (`fh1_fmod_native.cpp`), off by
  default (`fh1_fmod_native_parameq`).
- Cutscene movies: about 3 fps at base clocks and about 8 fps with GPU
  overclocking; CPU clock changes made no visible difference. The movie path is
  GPU-bound and separate from the native draw work. See
  [`docs/NATIVE-RENDERER.md`](docs/NATIVE-RENDERER.md#movie-playback-observed-2026-10-21).
