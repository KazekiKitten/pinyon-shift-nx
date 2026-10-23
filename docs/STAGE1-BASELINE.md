# Stage 1 — Baseline: material facts, evidence and the SDK merge decision

Status: **PC baseline built and booted on Linux/Vulkan; reference frames
captured.** Written 2026-10-18. Every claim below carries the command and its
observed result. Where a fact is taken from a repository document it is cited
by path.

Update 2026-10-18 15:26 UTC: §§7-8 record the successful Linux/Vulkan build,
the clean hidden boot and the captured reference frames. `main` was used (the
checkout is on `main`), so the build pins ShiftGlue `79d3e6f`, not `dev`'s
`b528422`; see §2.

## 0. Environment (evidence)

`uname -a`, `command -v`, `lspci`, `vulkaninfo`:

- Host: CachyOS Linux, kernel 7.2.9, x86-64, 8 logical CPUs, 15 GiB RAM.
- GPU: AMD Radeon RX 5700 XT (navi10) + Intel HD 4th-gen iGPU.
  `glxinfo -B` reports `AMD Radeon RX 5700 XT (radeonsi, navi10, ACO, DRM 3.64)`.
- Vulkan instance 1.4.363 present; RADV is the expected device for the
  pinyon-shift Vulkan build.
- Toolchain: clang 23.1.1, gcc, make, git, python3, wine, pacman + sudo.
  **cmake and ninja are not on `PATH`.** devkitPro is installed at
  `/opt/devkitpro` with `devkitA64`, `libnx`, `tools` (`elf2nro`, `uam`,
  `nxlink`) and CMake modules — so Switch cross-builds are possible here.
- PowerShell (`pwsh`) is **not** installed; the pinyon-shift Windows setup
  scripts cannot run as written. The repository also ships `tools/pinyon.py`
  for off-Windows work.

Implication: the Stage 1 PC baseline must be reproduced through the **Linux /
Vulkan** path (README `## Play` / `docs/LINUX.md` / `tools/pinyon.py`), not the
Windows D3D12 path the brief assumed. This is a change from the brief, not a
blocker: the current repository already supports Linux and the renderer is
Vulkan-first (`README.md` and `docs/NATIVE_PORT_BACKLOG.md` line 3: "Vulkan is
the sole supported graphics API. Direct3D 12 is legacy and unsupported").

## 1. Game input verified (evidence: `analysis/iso-verify.txt`)

| Property | Value |
| --- | --- |
| File | `../gamedump/Forza Horizon (USA) (En,Ja,…).iso` |
| Size | 8,738,846,720 bytes |
| SHA-256 | `83dfc7d0b58b804232385de6f794d9acb92b89a37cf13da14b824b286c824490` |

`config/supported-dumps.json` (`policy.match = exact_sha256_and_size`) expects
size `8738846720` and SHA-256 `83DFC7D0…4490` for
`forza-horizon-usa-ms-2505-retail-base`. **Exact match**, so the setup will
accept this dump. The entry also fixes the extracted catalog
(`config/supported-extracted-ms-2505.json`, 2,400 files) and the three
executables, which matters for the manifest in §3.

## 2. Pinned ReXGlue, its patches and its fork (evidence: `analysis/pinyon-fork.txt`)

The brief describes a `patches/rexglue` directory. **No such patch series
exists in the repository.** The pinned recompiler is a **git submodule fork**:

```
[submodule "thirdparty/shiftglue-sdk"]
	path = thirdparty/shiftglue-sdk
	url  = https://github.com/arcanite24/shiftglue-sdk
	branch = main
```

Pins (`git ls-tree <branch> thirdparty/shiftglue-sdk`):

| Branch | pinyon-shift tip | ShiftGlue pin |
| --- | --- | --- |
| `main` (current checkout) | `9331e453` "chore: release 0.6.0" | `79d3e6fae4b79e00def48a595c80f0eaa47fd2b6` |
| `dev` (the brief names this) | `45d1739c` "docs: record that stage 0 closed the clean-slate plan" | `b528422cb2e63c6163e9a3f3cc4cecd5a71fb721` |

The brief says branch `dev`; this checkout is on `main` at 0.6.0. **Recommend
working from `dev`**, which is 1 commit + the newer ShiftGlue pin ahead. The
Clean Slate research pages (`docs/CLEAN_SLATE_RESEARCH.md`,
`docs/CLEAN_SLATE_STAGE0.md`) exist only on `dev`, and its Stage 0 closed on
2026-10-18 — the same day as this work.

Fork facts (`sdk-pinyon`, checked out at the `dev` pin `b528422c`):

- Upstream merge-base: `c94f5ebdcb3c9d1a460ca48e04f9758448f8d518`
  ("Release v0.10.0", 2026-08-21) — so the fork is **upstream ReXGlue 0.10.0
  plus its own commits**, with clean git ancestry.
- **583 commits** since upstream 0.10.0; `git diff --shortstat`:
  **839 files changed, 300,316 insertions(+), 11,956 deletions(-)**.
- Commit types: 250 `feat`, 181 `perf`, 124 `fix`, 14 `refactor`, 7 `build`,
  6 `test`, 1 `chore`.
- Biggest scopes: `perf(vulkan)` 55, `feat(graphics)` 42, `perf(gpu)` 39,
  `feat(vulkan)` 35, `feat(d3d12)` 32, `feat(ui)` 21, `feat(gpu)` 19,
  `perf(renderer)` 17, `feat(codegen)` 16. The bulk is desktop/Vulkan/D3D12,
  DLSS-FSR, MoltenVK, Android/Adreno and fidelity-consistency work.

"The patches it applies" therefore = **the 583 commits on the fork**, not a
patch file. They are reproducible by `git checkout b528422c` (or `79d3e6f` on
`main`).

## 3. Manifest, modules, jump tables and setjmp (evidence: repo files)

`config/rexglue/pinyon_shift_manifest.toml`, pinned to `sdk_version = "0.10.0"`:

- Entrypoint: `default.xex` → `.local/generated/default`, includes
  `analysis/main-xex.toml`.
- Guest DLL modules (loaded with `XexLoadImage`), i.e. the `[[modules]]` the
  brief asks about — **the game has two**:
  - `SpeechFacade_default.xex` → `.local/generated/speech`, includes
    `analysis/speech-facade.toml`. Proven by M4 route trace `20260714T163417Z`.
  - `XMediaFacade_default.xex` → `.local/generated/xmedia`, includes
    `analysis/xmedia-facade.toml`. Proven by M2 trace `20260713T210328Z`.
- Game input and generated output deliberately resolve into ignored `.local`
  paths.

Related manifests in `config/rexglue/`: `pinyon_shift_v4_manifest.toml`
(title update v4), `pinyon_shift_abipoison_manifest.toml`,
`pinyon_shift_probe_manifest.toml`; plus `analysis/` and `analysis-v4/`
directories and `accepted-codegen-warnings*.json`. **Jump-table and
setjmp/longjmp entries and license/DLC settings were not located in these
manifest files** — they live in the analysis directory and host config, which
Stage 2 must catalogue. This is recorded as *not yet verified*.

License/DLC configuration that exists (evidence: repo files):

- `config/supported-dlc.json` — title `4D5309C9`, content type `00000002`,
  packages with `license_mask` per accepted payload (e.g. 1000 Club, December
  IGN Car Pack). Status strings: `import_verified_gameplay_pending`.
- `config/supported-title-updates.json` — world v4 (`4000D145`,
  `0000000C`→`0000040C`), status `applies_to_usa_base_native_port_pending`.
- Host-side DLC code: `src/dlc/`, `src/dlc_token_unlocks.*`,
  `src/dlc_treasure_map.*`; tools `tools/manage-fh1-dlc.py`.

### 3a. XDK build the game links — **2.0.21119** (evidence: `analysis/xex-libraries.txt`)

Read directly from the XEX2 static-library header with
`python3 -I tools/re/xex-libraries.py .local/game/base/*.xex`:

- `default.xex`: 25 static libraries. **`D3D9 2.0.21119.0` and `D3DX9
  2.0.21119.0`** (the linked Direct3D whose device layout stage 7/10 needs),
  plus `XGRAPHC`, `XBOXKRNL`, `XAPILIB`, `XAUDIO2`, `XHV2`, `XINP2`, `XFFB`,
  `NUI`, `ST`, `XPARTY`, `XNET`, `XONLINE`, `XMP`, `XMCORE`, `XAPOBA`,
  `NUIHNDL`, `MFPLAT 2.0.20693.0`, `LIBCMT 2.0.11886.0`, and two compiler
  builds (`C1`/`C2` 16.0.11886 and 16.0.10224, `LINK 10.0.11886.0`).
- `SpeechFacade_default.xex`: 8 libraries (`NUISP`, `NUIAUD`, …).
- `XMediaFacade_default.xex`: 6 libraries.

This agrees with the repository's `docs/D3D_RENDERER_RESEARCH.md` line 130
("D3D9 from XDK 2.0.21119 is linked into the executable, in two code bands").
The two compiler builds in one executable are the reason the guide's
prologue-style check (porting guide §2) matters: 16.0.11886 is the Xbox 360
build; 16.0.10224 is older and may indicate pre-built objects. The extra
modules found in §3 use the same XDK 2.0.21119 kernel/libc.

## 4. SDK fork comparison and the merge decision

### 4a. What each side is (evidence)

| | pinyon `shiftglue-sdk` | sa2-nx `sdk/` | nfsmw-nx `sdk/` |
| --- | --- | --- | --- |
| Base | ReXGlue 0.10.0 (`c94f5eb`), true git fork | ReXGlue 0.10.0 (`CMakeLists.txt` `VERSION 0.10.0`) | ReXGlue 0.10.0 |
| History | 583 commits on upstream | **re-rooted, 17 commits**, first is `Sonic Adventure 2 for Nintendo Switch, version 1.0.0` | re-rooted, 23 commits |
| Switch layer | none (`find -iname '*horizon*'` empty; no `switch_compat/`) | `switch_compat/` (`endian.h`, `netinet/`); Switch runtime under `src/system`, `src/graphics`, `src/audio`; app presets `sa2_switch*.toml` | same shape |
| Target | Windows/Linux/macOS/Android, D3D12+Vulkan | Nintendo Switch, NVK | Nintendo Switch, NVK |

Because the sa2-nx and nfsmw-nx SDKs are **re-rooted** (no shared git ancestry
with upstream ReXGlue or with pinyon), a `git merge` between them and pinyon's
fork is impossible. Any combination must be done at the **source-tree level**
(patch/cherry-pick selected commits onto the Switch tree, or the reverse).

### 4b. Decision

**Base = the nfsmw-nx / sa2-nx Switch SDK fork. Port onto it only pinyon-shift's
platform-neutral, game-relevant recompiler/runtime fixes, plus the FH1 host
code, manifest and config. Do not port the reverse.**

Reasons, each tied to evidence:

1. **The target needs the Switch layer, which only the Switch forks have.**
   pinyon's fork has no Switch platform layer (`find ... -iname '*horizon*'`
   empty, no `switch_compat/`). Porting the Switch layer onto pinyon means
   re-implementing and re-validating the whole Horizon runtime (memory,
   presentation, NVK, libnx, audio) — the opposite direction repeats the larger
   work.
2. **Most of pinyon's fork is desktop-only and irrelevant to the target.** 583
   commits are dominated by `vulkan`/`d3d12`/`renderer`/`upscaler`/`android`
   work (§2). Applying that to the Switch tree would be mostly dead weight and
   would drag in D3D12, DLSS/FSR and MoltenVK dependencies the Switch build does
   not use.
3. **The game-specific value is not in the SDK, it is in the pinyon repo.** The
   manifest/modules (§3), analysis TOMLs, host `src/`, config and tools are
   independent of which ReXGlue fork is underneath. They can be layered on the
   Switch SDK with little coupling.
4. **A git merge is not available, so a patch port is required either way.**
   Given that, porting the small platform-neutral subset forward onto the
   proven Switch base is strictly cheaper than porting the entire Switch base
   backwards.

**Subset of pinyon SDK commits to evaluate for porting** (candidates identified
by scope, to be confirmed per-commit in Stage 2): `feat(codegen)`/`fix(codegen)`
/`perf(codegen)` (PPC correctness: e.g. `fix(codegen): pack vpkuhus and vpkuwus
without aliasing vd`, `fix(codegen): recompile the lru-hint vector loads and
stores`, `fix(ppc): keep fp exceptions masked on every guest fpscr write`,
`perf(ppc): compute vmsum3fp128/vmsum4fp128 in simd`), `fix/kernel/thread`
(critical-section and global-lock fixes), and `fix/audio`/`perf(audio)` (XMA
decode). The desktop renderer, upscaler, `d3d12`, `vulkan`-device, MoltenVK and
Android/Adreno work is **out of scope** for the Switch layer and stays out.

**Caveat recorded honestly:** this decision rests on scope counts and the
platform-layer presence, both verified above. It has **not** yet been validated
by compiling either tree, and the brief's Stage 4 (a native PC renderer from
masseffect-nx via banjo-nx) may prefer pinyon's own native-executor lineage
instead. That choice does not change the SDK base decision; it changes which
renderer is carried. It is deferred to Stage 4.

## 5. What is done, what is not

Done:

- ISO matches the supported retail dump exactly (§1).
- Pins, fork size and patch nature recorded (§2).
- Manifest, the two guest modules, DLC and title-update configuration recorded
  (§3).
- SDK comparison and merge decision written, with evidence and reasons (§4).
- The PC baseline is **built and boots** on Linux/Vulkan on this machine (§7).
- Reference frames for boot, menus, a driving segment and the opening cutscene
  movie are captured and hashed (§8).
- The XDK build is identified from the XEX header: **2.0.21119** (§3a).

Not done / not verified (do not treat as done):

- The `[functions]` list, jump-table entries and setjmp/longjmp addresses were
  not located; the manifest does not carry them. They are in
  `config/rexglue/analysis*/` and must be catalogued in Stage 2.
- The baseline was built from `main` (ShiftGlue `79d3e6f`), not `dev`
  (`b528422`); `dev` was not built.
- **A true race was not captured.** The race routes need the qualified AppData
  fixture save, which is not on this machine; the opening drive (a driving
  segment with HUD and traffic) is the captured stand-in.
- The reference is **stills, not video**. The repository's `tools/make_video.sh`
  named in the brief does not exist; the deterministic frame routes were used
  instead. A continuous MP4 capture was not produced.
- The sa2-nx/nfsmw-nx SDKs were not compiled, and no pinyon commit was applied
  to the Switch tree.
- The preview-limit bugs named in the brief (gameplay audio gap, car
  shake/jitter, collisions, Mustang-vs-Mustang camera jump) were **not
  reproduced or investigated** here; they are Stage 2 work.

## 6. Proposed next actions

1. Rebuild from `dev` (`b528422`) so the baseline matches the branch the brief
   names, then re-capture the frames and record any difference.
2. Catalogue `config/rexglue/analysis*/` (functions, jump tables,
   setjmp/longjmp) and write it into this folder (Stage 2 groundwork).
3. Confirm the §4b subset by attempting each candidate commit on the Switch
   tree (compile results).
4. If a real race/cutscene reference is required, obtain a qualified save seed
   (`tools/create-render-seed.py`) from the user and re-run the race and FMV
   routes.

## 7. PC baseline build (Linux/Vulkan) — evidence

Command: `python3 tools/pinyon.py setup --iso "<ISO>" --jobs 8 --json`, run from
`~/.local/share/PinyonShift/source/0.1.1` (the setup source the launcher
installs). It verified the disc, provisioned a pinned LLVM 20.1.8 and the Steam
Runtime SDK toolchain, extracted the disc, generated and compiled the game.

Result: `::pinyon::{"stage": "play", "percent": 100, "message": "Ready to
play"}`. Evidence in `analysis/build-record.txt` and `analysis/setup-state.json`.

Build output (`out/build/linux-amd64-release/`):

| File | Bytes |
| --- | --- |
| `pinyon_shift` | 121,678,832 |
| `librexruntime.so` | 17,867,384 |
| `librexgpu-fh1.so` | 8,925,112 |
| `libpinyon_shift_SpeechFacade_default.so` | 15,113,920 |
| `libpinyon_shift_XMediaFacade_default.so` | 18,481,488 |

Generated code: `default` 263 MB, `speech` 30 MB, `xmedia` 42 MB. Build label
from the runtime: `Pinyon Shift 0.6.0 | ShiftGlue 79d3e6f | Linux Release`,
`cpu_baseline=v3`, `executable_sha256=580EE874…4D8B`.

Boot test: `python3 tools/pinyon.py launch --hidden --timeout 90 --json`
(no window, audio muted). The runtime log `analysis/runtime-hidden-boot.log`
shows `process.start` → shader preparation ("3 storage files kept") →
`process.shutdown` / "Execution complete", with **no crash, fatal, assert or
error lines**. The native Vulkan executor logged 3000 frames, ~210,388 draws,
15 surfaces; the shader cache logged 29,100 loads / 28,202 hits, 0 uncacheable,
0 mismatches. Audio reported `native_output_mode`.

## 8. Reference frames — evidence

Command: `python3 tools/run-fh1-render-test.py
config/render-tests/fh1-opening-sync.fh1test --fresh-profile --hidden
--build-directory <install>/out/build/linux-amd64-release --game-root
<install>/.local/game/base --output port/frames/opening --record-baseline
--baseline-dir port/baseline --timeout 900` (run from the repository).

Captured four 1280×720 PPM frames (converted to PNG under
`port/frames/opening/png/`), hashes in `analysis/baseline-frames.md5`:

| Frame | Content (visually confirmed) |
| --- | --- |
| `press-start` | Title screen: mountain vista, man and car, "FORZA HORIZON — PRESS START" |
| `single-player` | Single-player menu |
| `opening-drive` | Viper on the opening route: HUD speedometer/gear, minimap, traffic, shadows |
| `opening-drive-later` | Later frame of the same drive |

Cutscene/movie reference (route `config/render-tests/fh1-fmv.fh1test` with
`--include-opening-movies --fresh-profile --hidden`, output
`port/frames/fmv/`):

| Frame | Content (visually confirmed) |
| --- | --- |
| `opening-180` | Opening FMV, dashboard/interior close-up |
| `opening-300` | Opening FMV, dashboard/interior close-up (later) |
| `opening-60` | **Blank** — the runner reported "blank or degenerate output"; the movie has not faded in yet at frame 60 |

So the reference set now covers **boot, menus, a driving segment and a
cutscene (the opening movie)**. A true race is still missing (needs the
qualified save seed) and is the one remaining Stage 1 capture gap.

The runner reported `image comparison failed for press-start` because
`--record-baseline` did not write a baseline PPM; the captured frames themselves
are valid. Making that flag produce baselines for later `compare_video.py`
checks is a follow-up, not a blocker.

Note for naming: the project is kept neutral (`PinyonShift-NX`); the game's
title and the creators' names appear only where the game itself renders them.
