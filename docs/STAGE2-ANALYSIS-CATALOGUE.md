# Stage 2 — Missed-code sweeps: analysis catalogue

Status: in progress. Every number below is read from the pinyon-shift 0.6.0 tree
or from the installed baseline at
`~/.local/share/PinyonShift/source/0.1.1/.local/`. Nothing here is inferred.

## 1. What Stage 2 has to establish

Stage 2 proves that the static recompilation covers *all* guest code, not just
the code the automatic pass happened to find. It has two halves:

1. Catalogue the analysis configuration pinyon-shift already carries (this
   document).
2. Re-run the missed-code sweep tooling against the Forza codegen and confirm
   there is no unreviewed gap, unreachable pointer, unfixed jump table, or
   uninitialised register read.

## 2. Analysis configuration inventory

Manifest: `config/rexglue/pinyon_shift_manifest.toml` — entrypoint `default.xex`
plus modules `SpeechFacade_default.xex` and `XMediaFacade_default.xex`.

Per-image analysis TOMLs live in `config/rexglue/analysis/`:

| File | Lines | Contents |
| --- | --- | --- |
| `main-xex.toml` | 1824 | `default.xex`: 197 midasm hooks, 113 explicit function boundaries, 333 rexcrt mappings, root codegen options |
| `fh1-post-processing.toml` | 34 | included by `main-xex.toml`; 4 midasm hooks (motion blur + depth of field) |
| `speech-facade.toml` | 7 | `SpeechFacade_default.xex`: 1 function boundary |
| `xmedia-facade.toml` | 10 | `XMedia_default.xex`: 2 function boundaries |

A parallel v4 analysis set exists at `config/rexglue/analysis-v4/` (not used by
the baseline build).

### 2.1 `main-xex.toml` root keys

Code flow/ABI:
- `setjmp_address = 0x82A81E80`, `longjmp_address = 0x82A81950`
- `cr_as_local = true`, `ctr_as_local = true`, `xer_as_local = true`
- `interior_resume = false`, `direct_calls_bypass_thunk = true`
- `fold_rodata_loads = true`
- `host_local_register_saves = true`
- `host_local_lr = true`, `host_local_lr_keep = [0x82BC5870]`
- `host_overridden_functions = [0x82438EA8, 0x830F2210, 0x82A6D7D8, 0x8245DBE0, 0x82F86498]`

Physics specialisation — the same four-address set drives four options
(`register_locals_functions`, `fixed_fp_mode_functions`,
`single_precision_functions`, `reference_functions`), with
`reference_sample_every = 40`:
`0x82CB6308, 0x82CB7A88, 0x82CB9F98, 0x82CBA9F8, …` (the codegen log reports
19 functions in each set).

### 2.2 Midasm hooks (197 + 4)

Named host companions injected mid-function. Clusters observed:

- `PinyonShiftUiCompanion*` — 11 hooks (memory stream, pause model/action,
  button construct/destroy/release, input match, file read).
- Car/upgrade: `PinyonShiftInitializeCarUpgradeViews`,
  `PinyonShiftRequireTyrePhysicsRecord`, `PinyonShiftTraceUpgradeView*` (2),
  `PinyonShiftTraceDlcSqlPrepare`, `PinyonShiftReadRallyEntryPosition`.
- Graphics/gamma: `PinyonShiftObserveGraphicsFrame`,
  `PinyonShiftGammaRampPwl{Begin,Built,DeviceSet}`,
  `PinyonShiftGammaRampLinear{Begin,Built}`,
  `PinyonShiftObserveTitleDrawEmitterBegin`,
  `PinyonShiftObserveTitleDrawPacketPublish`.
- Post-processing (from the included file): `PinyonShiftDisableMotionBlur`
  (0x82D7894C) and `PinyonShiftDisableDepthOfField` (0x8245B494, 0x8245846C,
  0x8245849C). These mirror xenia-canary game patches for hash
  `D48ABF1704CE5C4A`; they only diverge when their runtime setting is true.

### 2.3 Function boundaries (113 + 3)

Explicit `[functions."ADDR"]` size overrides fix gap-fill mistakes. The
comments carry the evidence class, e.g.:

- Gap-fill splits of leaf/tail thunk tables: `82B1ABD0`, `82B3B8B0`,
  `82CF87F8`, `82F1ED30`, `82F5CC68`, `82F76188`, `82F762A0`.
- Context-restore after a `KeBugCheck` noreturn path: `830ED910` (0x40C).
- **M4 runtime-proven** indirect target: `829CB048`, reached from the callback
  dispatcher at `0x829C9528` (outer LR `0x829C4058`) during run 97; the middle
  entry of the three-address table at `0x8328C134`; returns at `0x829CB074`,
  next table target at `0x829CB078`.

The facade files add `890E2FA0` (speech, 0x18) and `88055B80` / `882435D8`
(xmedia, 0x10 each).

### 2.4 `[rexcrt]` mappings (333)

Recompiled-C-runtime remaps (memcpy, memmove, memset, fibers, …) for the CRT
functions the guest links in. 333 address→name pairs in `main-xex.toml`.

## 3. Installed baseline codegen output

From `~/.local/share/PinyonShift/source/0.1.1/.local/`:

- Extracted guests: `game/base/{default.xex, SpeechFacade_default.xex,
  XMediaFacade_default.xex}` (default.xex 20,856,832 bytes).
- Generated code: `generated/{default, speech, xmedia}/`
  (`pinyon_shift_funcs.*.h`, `pinyon_shift_folds.cpp`, `module_registry.cpp`,
  `dll_targets.cmake`).
- Recompiler checkout: `rexglue/` (git; SDK 0.10.0-dev).
- Logs: `logs/{codegen.log, codegen-console.log}`.

### 3.1 `build.json`

`schema_version 3`, `Release`, `cpu_baseline v3`,
`guest_executable_sha256 = DB40DF605ADE49A612B35A7A24C38F6004BCB17A88ED6B48288DE16DF9E3987C`,
`rexglue_commit = 79d3e6fae4b79e00def48a595c80f0eaa47fd2b6`.

### 3.2 Codegen summary (`codegen-console.log`)

- 3 modules recompiled; **655 files written, 0 unchanged, 0 deleted**;
  default 291.8 s, speech 26.2 s, xmedia 27.0 s; total 295.1 s.
- `host_local_register_saves`: 22,030 of 22,968 prologue functions keep rN–r31
  in host locals.
- `host_local_lr`: 55,029 of 56,799 LR-saving functions keep the slot in a host
  local; 33,354 reloads rewritten.
- Physics specialisation: `register_locals_functions` 19/19; `fixed_fp_mode`
  19 functions (177 flush-mode toggles guarded or dropped); `single_precision`
  19 functions, 27 fused multiply-adds; 33 reference save-area stores rolled
  back but not compared.

## 4. Accepted codegen warnings (reviewed)

`config/rexglue/accepted-codegen-warnings.json` (schema v1, policy
`fail_on_unrecognized_warning_and_missing_expected_warning`) lists exactly three
patterns; the installed log produces six matches (2 per pattern):

1. `oversized-function-8241A370` — "Function 0x8241A370 is 2640738 bytes,
   exceeds max_file_size_bytes (1048576)".
2. `bdz-outside-function-82AD8138` → `82AD836C`.
3. `bdz-outside-function-82AD813C` → `82AD836C`.

`tools/verify-codegen-log.py` run against the installed `codegen.log` returns
`warning_count 6`, all accepted — i.e. no unreviewed codegen warning.

**Discrepancy resolved (was 110,012 B vs 2,640,738 B).** `site/findings/
executable.toml` says the largest `.pdata` unit is **110,012 bytes** at
`sub_8241A370` (finding "largest function", v4 `sub_8244A320`), while the
recompiler warned about **2,640,738 bytes**. These are different units. In
`src/codegen/codegen_writer.cpp`: line 440 is `std::string code =
fn->emitCpp(emitCtx);` (generated C++ text) and line 469 is `if (code.size() >
maxFileBytes)` where `maxFileBytes` is the cvar `max_file_size_bytes`
(`codegen_flags.cpp`, default 1,048,576). The warning therefore measures the
**generated C++ source text**, not guest code. 110,012 guest bytes ≈ 27,503 PPC
instructions → ~2.6 MB of generated C++ is a normal ~24× expansion. No evidence
of swallowed adjacent code; the allowlist reason ("known deterministic large
translation unit") is accurate. `sizes` also feeds `partition.Assign(sizes,
maxFileBytes)` (line 545); a single function cannot be sharded, hence the
warning rather than a split.

The two `bdz` warnings are the switch's out-of-range CTR cases (selectors 6 and
7), confirmed by finding `82AD8138, 82AD813C, 82AD836C`.

## 5. Sweep tooling and where it runs

The updated brief points at the sa2-nx / nfsmw-nx sweep tools. They are
game-agnostic but written against the **sa2-nx repo layout** (`out/`,
`app/generated/default`, `app/overrides.toml`). Map:

| sa2-nx tool | Purpose | pinyon equivalent / target |
| --- | --- | --- |
| `find_gaps.py` | list code gaps no function claimed | `tools/find-fh1-missing-thunks.py` |
| `gap_fixpoint.py` | repeat structural gap scan to fixpoint | (structural scan of analysis TOMLs) |
| `gap_classify.py` | classify gap candidates | — |
| `runtime_gap_resolver.py` | classify runtime invalid-function failures | `tools/find-fh1-missing-thunks.py` |
| `pointer_fixpoint.py` / `pointer_audit.py` / `pointer_scan.py` | code pointers in data (vtables, callbacks) | — (produced `[functions]` entries) |
| `switch_check.py` | validate jump tables, emit `[[switch_tables]]` | — (`82AD8138` finding) |
| `read_before_write.py` | flow-sensitive uninitialised read / noreturn | `tools/check-nonlocal-jumps.py` |
| `check_switch_build.py` / `switch_compile_check.py` | Switch-specific build checks | future (Stage 5) |

`~/PinyonShift-NX/nfsmw-nx/tools/` carries Spanish-named equivalents
(`huecos.py` = gaps, `lee_antes.py` = read-before-write) with the same intent.

The sa2-nx tools need path adaptation to run here: point `--image` at the
recompiler's image artefact, `--gen` at `.local/generated/default`, and write
`[[switch_tables]]`/overrides into the pinyon analysis TOMLs rather than
`app/overrides.toml`.

## 6. Structural gap scan (run 2026-10-18)

Ran sa2-nx's `find_gaps.py` against the installed generated tree
(`.local/generated/default`), writing to `port/analysis/gaps/`:

- Functions: **76,494**; gaps total: 38,046; gaps ≥ 8 B: **738**; bytes in gaps:
  180,348. Distribution is dominated by 4-byte gaps (37,308, alignment/returns)
  and 8–12-byte gaps (380 + 190).
- A 4-byte `blr` constrains this: most small gaps are padding or the trailing
  return that a function boundary already consumed.

Then a scratch ReXGlue codegen
(`port/analysis/gaps/pass1/`, 738 candidates declared as `[functions."…"]
size = 0x…`, run via the pinned host tool
`.local/rexglue/out/linux-amd64/Release/rexglue codegen`, 339 s, exit 0) so the
candidate code could be inspected:

- `gap_classify.py` tier 1: **367 ACCEPT**, 193 no-code/stub, 172 no terminator,
  6 extends-beyond-gap; tier 2: **0**.
- After the `gap_fixpoint.py` final filter (reject r1 / stack / LR / undefined-
  at-entry): **258 candidates**.
  - **61 with a real body** — `this`-adjustor thunks
    (`addi r3,r3,-N ; b 0x…`), vtable call thunks
    (`lwz r12,0(r3) ; lwz r11,OFF(r12) ; mtctr r11 ; bctr`), and tail branches.
    These are the same class as pinyon's manual `[functions]` entries and look
    like genuinely unclaimed code.
  - **197 single-`blr`** — a one-instruction function in an 8-byte gap. Needs
    review: either a trivial virtual stub or the trailing return of the
    preceding function (boundary one instruction short).

Evidence: `port/analysis/gaps/{report.txt, candidates.toml, selected.txt,
pass1/acc.txt, pass1/acc-final.txt, pass1/codegen.log}`.

Not yet done: fixing the 61+197 into pinyon's analysis config (a change, not a
sweep, and it risks over-declaration).

## 6a. Guest image for the image-based sweeps

`switch_check.py` and `pointer_audit.py` need the flat guest image at
`0x82000000`. The pinned rexglue host tool has no image-dump subcommand, but the
already-built `pinyon_shift_fh1_archive_extract --xex-image` (source
`tools/fh1_archive_extract.cpp:260`, CMake target built at
`out/build/linux-amd64-release/pinyon_shift_fh1_archive_extract`) produced
`port/analysis/images/default_image.bin` — 23,199,744 B. Executable ranges
(via `generate-fh1-v4-addresses.py:executable_ranges`): main
`0x823E0000:0x831EE634`, plus `0x831EE800:0x831EF18C` and
`0x831EF200:0x831EF59C`.

## 6b. Jump-table scan (run 2026-10-18)

`switch_check.py` over the main code range against the installed generated tree
(`port/analysis/switch/`):

- bctr census: absolute 260, byte 109, half 54, indirect 1729; generated: 421
  switches, 1342 indirect.
- **truncated: 1 (crash risk)** — `sub_829EB348` at bctr `0x829EB474` reads the
  byte table at `0x820C5DA8` with bound 64 (`0x829EB44C`); the generator emitted
  only **24 cases**. Taking case ≥ 24 hits `__builtin_trap()`. Fix written to
  `port/analysis/switch/switch-fix.toml` (`[[switch_tables]] address =
  0x829EB474, register = 10`, 64 labels).
- wrong targets: 0; missed: 0; extra cases: 4 (harmless); table jumps with no
  generated code: 0.
- no bound in the code: 24 (absolute tables right after their bctr, 12 cases
  each) — review by hand. odd shapes: 14 — review by hand.

## 6c. Code-pointer scan (run 2026-10-18)

`pointer_audit.py` (adapted via a wrapper that overrides its `ROOT`/`MODULES`)
against the image and generated tree (`port/analysis/pointer/`):

- 76,885 registered functions. Pointers to non-function-starts: SEH scope 155,
  EH state map 1544, jump table 421, other 301, built in code 12,
  **vtable-like 59**.
- The 59 vtable-like are explicit crash risks ("Call to invalid or unregistered
  function"): addresses in gaps that ≥2 neighbouring vtable words point at, e.g.
  `0x82A95FD0`/`0x82A95FD8` (this-adjustor thunks, from `0x820DC9BC`),
  `0x82AA9B28` (from `0x820DE6C8`), `0x82E873C0` (from `0x8224F388`).
- **33 of the 59** are also found by the gap scan — the two independent sweeps
  agree. Consolidated candidate set: **87 addresses**
  (`port/analysis/stage2-candidates.txt`).

This is the main Stage 2 outcome: the automatic analysis misses at least 59
referenced entry points, 33 corroborated by two independent methods.

## 6d. Fixes adopted and verified (2026-10-18)

Adopted into `pinyon-shift/config/rexglue/analysis/stage2-fixes.toml`, included
from `pinyon_shift_manifest.toml` (entrypoint `includes`):

- **1 truncated jump table** — `[[switch_tables]] 0x829EB474` (register 10,
  64 labels) for `sub_829EB348`.
- **134 function declarations** — the 133 thunks `find-fh1-missing-thunks.py`
  reports as referenced-but-unemitted (true extents), plus `0x83102428` found
  only by `pointer_audit.py`. Sizes are clipped to the next registered or
  newly-declared boundary (13 clips; no drops). The 17 gap-scan-only candidates
  were deliberately **not** adopted: `82B2EF04 / 82B2EFDC / 82F85FDC /
  82F9CEDC / 83016D94` are in-function jump-table labels, and declaring them
  split functions and broke their switches.
  - **Correction (relink):** 16 of the 133 (`0x831EDB0C … 0x831EE34C`, the
    tail-end of the main range) are **import thunks** — the codegen log records
    `[functions] 0x… outranked by import` for each. `find-fh1-missing-thunks.py`
    only reads the function-init table for its "registered" set, so it does not
    know about imports and over-reports them. Declaring them as functions made
    the init table register `sub_XXX` while the import took precedence over the
    body, producing 16 undefined symbols at link. They were dropped
    (`stage2-fixes.toml` now carries **118** thunks + the 1 switch table), and
    the link succeeds.

Re-codegen (scratch, `port/analysis/verify1/`, 341 s, exit 0) and re-sweep:

| Check | Before | After |
| --- | --- | --- |
| `find-fh1-missing-thunks` not emitted | 133 / 11,669 | **0 / 11,669** |
| `pointer_audit` vtable-like non-starts | 59 | **0** |
| `switch_check` truncated tables | 1 | **0** |
| `switch_check` wrong targets | 0 | 1 (see below) |
| `find_gaps` gaps ≥ 8 B | 738 | 692 |

Residual (documented, no silent failure): the repaired table `0x829EB474` has
4 case targets (`0x829EB780/788/798/800`) that lie **inside sibling functions**
`sub_829EB688` / `sub_829EB7E0` and cannot be emitted as labels; the generator
emits `REX_FATAL("Jump target … unresolved")` for those 4 cases. This is
strictly better than before (cases 24–63 previously hit `__builtin_trap()`): 36
of the 40 recovered cases now dispatch correctly, 4 fail loudly.

## 6e. Installed-baseline refresh and relink (2026-10-19)

Config copied into `~/.local/share/PinyonShift/source/0.1.1/config/rexglue/`
and `rexglue codegen --ignore-stamp` re-run:

- First attempt (134 thunks): codegen exit 0 but `ninja pinyon_shift` **failed**
  at link with 16 undefined symbols (`sub_831EDB0C … sub_831EE34C`), all
  `outranked by import` (see §6d correction).
- After dropping the 16 import thunks (118 thunks): codegen exit 0
  (`77 written, 578 unchanged`) and `ninja pinyon_shift` **succeeded**
  (binary 121,708,448 B).

Verification of the rebuilt baseline:

| Check | Result |
| --- | --- |
| `ninja pinyon_shift` | **link OK** |
| hidden boot (`tools/pinyon.py launch --hidden`) | **no fatal / assert / REX_FATAL** |
| frames rendered in a 180 s cap | **10,200** (game loops at menu; launcher reports its cap as `timeout`, not a crash) |
| shader cache mismatches | **0** |
| deterministic smoke (`tools/run-fh1-render-test.py … fh1-smoke`) | **result: pass**, frame 300 captured, clean self-termination, 60 fps, 0 command-buffer stalls |

Evidence: `port/analysis/runtime-hidden-boot-stage2*.log`,
`port/analysis/render-smoke-stage2.log`,
`port/analysis/stage2-smoke/{boot.ppm,result.json}`.

Note: the rebuilt binary still reports the stale embedded build label / sha
(`built 2026-10-18 15:21`, `580EE874…`) in `process.start`; the build-info
header is not regenerated by the incremental relink. Cosmetic only.

## 7. Next actions

1. Run `read_before_write.py` in the appropriate mode after the specialised
   codegen options are confirmed.
2. Hand-review the remaining open items from the jump-table scan (24 no-bound
   tables, 14 odd shapes) and the 197 single-`blr` gap thunks (expected benign
   tail thunks), recording any that need declarations.
3. Re-run `verify-codegen-log.py` against the refreshed `codegen.log` and
   confirm the accepted-warning set is unchanged.
4. Advance to Stage 3 (platform-independent host layer).
