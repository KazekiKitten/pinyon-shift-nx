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
