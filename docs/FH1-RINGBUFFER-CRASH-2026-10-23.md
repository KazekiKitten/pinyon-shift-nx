# FH1 ringbuffer crash and the 2026-10-23 GPU test

Status: investigation record, 2026-10-23.

Build tested: `82ab4dd1de2f999958b0b7a99bea71a9bb8a3346ed85623d0c0b6bdc58f065b5`
(`fh1.nro`, 108,792,005 bytes).

**Verdict:** the four test changes did what they were supposed to do, but they
did **not** cause the crash. The same crash signature is present in the older
build (`fh1_007.log`): same ringbuffer failure, same guest `0x14` fault, same
late-scene timing. The crash is a pre-existing command-processor/guest
synchronisation bug. The ringbuffer and ZCULL changes are effective and should
be kept; `occlusion_query_enable = false` is probably harmful and should be
re-tested before keeping it.

**Post-preflight update (2026-10-23 01:06-01:23):** two runs on the diagnostic
build (`207be8772623ff6b495faa144426ab569dd9c60ed660055b02a232747ff94ba7`)
reached frame 3000 and frame 2400, including the 1.x fps / ~3000-draws-per-frame
scene, with **no** `PRIMARY RINGBUFFER`, `incomplete packet`, `ExecutePacketType3
overflow`, or guest access violation. The earlier `0x1103` crash log predates
the preflight fix. Both `gpu_publish_read_pointer_early=true` and `false`
survived, so early RPTR publication is not supported as the cause. Best current
explanation: the non-consuming preflight prevents the host from treating the
unpublished `FFFFFFF0` header as a real 0x10000-byte packet. Caveat: both runs
had `fh1_transfer_volume`/`fh1_resolve_volume` enabled, which adds string/map
work and changes timing; a clean run with both off is the remaining
confirmation.

---

## 1. What was tested

The test followed the first list from the earlier renderer review:

| # | Change | Result |
| --- | --- | --- |
| 1 | Disable occlusion queries (`occlusion_query_enable = false`) | Applied. No crash benefit. Likely increases late-scene draw count. |
| 2 | Disable end-of-primary-buffer submit (`vulkan_submit_on_primary_buffer_end = false`) | Applied. No crash benefit proven. Needs A/B. |
| 3 | Check `VkPipelineCache` / Mesa cache settings | Checked. No app `VkPipelineCache`; no Mesa disk cache configured. Not changed. |
| 4 | Remove `TRANSFER_DST` from normal depth surfaces | Applied. ZCULL now creates depth planes. |
| 5 | Make full-clear transfer skip survive clear flushing | Applied. `transfer_skipped_full_clear` now appears. |

Profiling was turned on for the run:

```toml
fh1_native_gpu_profile = true
fh1_draw_cpu_profile = true
```

Other relevant TOML values in the tested build:

```toml
occlusion_query_enable = false
vulkan_submit_on_primary_buffer_end = false
fh1_msaa_single_sample = true
fh1_fold_clears = true
fh1_surface_rows_on_demand = true
fh1_raw_transfers = true
fh1_transfer_skip_stencil = true
fh1_skip_transfers_before_full_clear = true
fh1_resolve_to_textures = true
fh1_resolve_partial_textures = true
fh1_coalesce_resolves = true
fh1_skip_draws_without_effect = true
fh1_texture_fingerprint = true
fh1_texture_watch = true
fh1_d3d_draw = 2
fh1_d3d_slice = 2
```

The build was produced with:

```sh
/home/kaze/PinyonShift-NX/pinyon-shift/.local/toolchain/ninja-1.13.2-linux/ninja \
  -C /home/kaze/PinyonShift-NX/port/switch/app/out/sw fh1 -j4
```

The NRO was copied to the SD card with `gio copy` (direct MTP reads fail with
`Input/output error`). The SD copy's size was verified; its hash could not be
read through MTP.

---

## 2. Runs used for this analysis

The emulator clock in the logs reads `2053-06-30`; the real test date is
2026-10-23.

| Run | Build | Log window | Reached | Outcome |
| --- | --- | --- | --- | --- |
| `fh1_007` | old, before this test | 07:16:37 - 07:22:36 | frame 2400 | ring overflow, guest fault `0x14` |
| `fh1_008` | new | 10:10:37 - 10:15:44 | frame 2400 | ring overflow, guest faults `0xAF`, `0x117` |
| `fh1_009` | new | 10:19:55 - 10:24:45 | frame 2400 | ring overflow, guest fault `0x14` |

The old run `fh1_007` is important evidence: it had no
`transfer_skipped_full_clear` counter and no GPU profile, so it predates the
2026-10-23 changes. It still crashes in the same place.

Relevant logs:

- `/home/kaze/PinyonShift-NX/logs/fh1_008.log`
- `/home/kaze/PinyonShift-NX/logs/fh1_009.log`
- `/home/kaze/PinyonShift-NX/logs/rex/rex_stderr.log`
- `/home/kaze/PinyonShift-NX/logs/rex/rex_perfil.log`
- `/home/kaze/PinyonShift-NX/logs/rex/rex_crash.log`
- `/home/kaze/.local/share/Trash/files/fh1_007.log` (old build)
- `/home/kaze/.local/share/Trash/files/fh1_006.1.log` (older performance profile)

---

## 3. What the changes achieved

### 3.1 ZCULL depth planes now exist

`rex_stderr.log` contains actual depth planes:

```text
[nvk] ZCULL: plano de 64224 bytes para profundidad 640x1024 (align 1024)
[nvk] ZCULL: plano de 65504 bytes para profundidad 1280x768 (align 1024)
[nvk] ZCULL: plano de 64224 bytes para profundidad 640x1024 (align 1024)
[nvk] ZCULL: plano de 64224 bytes para profundidad 1280x512 (align 1024)
[nvk] ZCULL: plano de 64224 bytes para profundidad 640x1024 (align 1024)
[nvk] ZCULL: plano de 64224 bytes para profundidad 1280x512 (align 1024)
[nvk] ZCULL: plano de 64736 bytes para profundidad 80x8192 (align 1024)
[nvk] ZCULL: plano de 64224 bytes para profundidad 640x1024 (align 1024)
```

Before this change the same log reported:

```text
[nvk] ZCULL: SIN plano para profundidad ...: usos incompatibles (TRANSFER_DST?)
```

The fix is in `CreateSurfaceImage` (`fh1_native_executor.cpp:730`): normal depth
surfaces no longer request `TRANSFER_DST`; the grown image in `EnsureSurfaceRows`
is the only depth surface that still does (`:836`). The driver condition in
`mesa-switch/src/nouveau/vulkan/nvk_image.c` accepts
`DEPTH_STENCIL_ATTACHMENT | READ_ONLY_IMAGE_USAGE`, and `TRANSFER_DST` was the
disqualifier.

This confirms the ZCULL workaround is now reaching the depth format the game
actually uses. It does **not** prove ZCULL improves frame time yet; that needs a
clean A/B with the same scene.

### 3.2 Full-clear transfer skip now fires

The old build had no counter. The new runs report it:

```text
transfer_skipped_full_clear=18103
```

at frame 2400 in `fh1_009`, and `17733` in `fh1_008`. The mechanism is
`Surface::clear_full_rows`, set when a full-width clear is folded, kept after
`pending_clears` is flushed, and consumed by `PrepareTargets`. This is the
intended behaviour and should stay.

### 3.3 Occlusion queries and end-of-buffer submit

No crash improvement. The crash also exists in the old run, which predates this
test and most likely used the default (`occlusion_query_enable = true`), so
occlusion is not the cause. The old TOML was not preserved, so this is an
inference from the run's date and counters, not a byte-for-byte config check.

There is a performance concern: when `occlusion_query_enable = false`, the
fallback path in `CommandProcessor::ExecutePacketType3_EVENT_WRITE_ZPD`
(`command_processor.cpp:1422`) reports the fixed
`query_occlusion_fake_sample_count` (default `1000`) for every query. That means
"visible", so the game cannot cull with occlusion results. The late-scene
`draw_stencil` count in `fh1_009` reaches `96,051`, compared with `11,283` in
the old `fh1_007` at the same frame number. The scenes are not identical, so
this is not proof, but it is exactly the kind of overdraw that disabling
occlusion produces.

**Recommendation:** re-enable `occlusion_query_enable` and A/B the same route
before keeping it disabled. Keep `vulkan_submit_on_primary_buffer_end =
false` only if an A/B shows it helps; it is not a crash fix.

### 3.4 Measured frame cost

The new profiling windows:

| Run | Frame | Draws | `draw_stencil` | Surfaces | Frame ms | Transfers | Resolves | Full-clear skipped |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 008 | 600 | 43,887 | 3,065 | 18 | 42.682 | 16.421 | 17.627 | 2,065 |
| 009 | 600 | 47,738 | 3,127 | 18 | 49.672 | 18.804 | 20.464 | 2,601 |
| 008 | 1200 | 111,087 | 6,065 | 18 | 111.752 | 41.962 | 46.297 | 8,065 |
| 009 | 1200 | 114,938 | 6,127 | 18 | 111.708 | 41.961 | 46.295 | 8,601 |
| 008 | 1800 | 178,287 | 9,065 | 18 | 111.751 | 41.959 | 46.298 | 14,065 |
| 009 | 1800 | 182,138 | 9,127 | 18 | 111.711 | 41.957 | 46.297 | 14,601 |
| 008 | 2400 | 264,450 | 12,502 | 31 | 99.217 | 40.557 | 39.118 | 17,733 |
| 009 | 2400 | 376,052 | 96,051 | 38 | 115.159 | 49.875 | 41.258 | 18,103 |
| 007 | 2400 | 242,739 | 11,283 | 18 | n/a | 60,094 | 61,168 | n/a |

The older `fh1_006.1` profile, for reference, reported `129.575 ms` frame,
`62.393 ms` transfers and `44.445 ms` resolves. The gain is real but modest:
transfers dropped by roughly 20%, resolves by roughly 7%, and the frame-time
sample at frame 2400 dropped from about 115-130 ms to 99-115 ms. It is not a
direct A/B because the scene changed.

The `fh1_009` frame-2400 window is the worst case: 96k stencil draws, 38
surfaces, and pipeline creation still happening. It is also the window where
the crash occurs.

Draw CPU for the new build is not a clean comparison either, because
`fh1_draw_cpu_profile` was enabled. The instrumented samples show:

```text
FH1 draw CPU (20000 draws): total 106.9 us/draw
  shaders 4.1 textures 53.3 targets 9.0 pipeline 1.3 bindings 2.8
  vfetch 6.0 draw 30.3
```

The texture bucket dominates in the car/garage scene (`53.3 us/draw`), while
the pipeline bucket is only `1.3 us/draw`. That is a texture-cache problem, not
a pipeline-compilation problem. The old race profile was `24-39 us/draw`, so the
instrumented garage/loading scene is a different regime.

Frame 600 is about `50 ms` (20 fps); frames 1200-1800 are about `112 ms`
(9 fps); frame 2400 is `99-115 ms` (8-10 fps). The target is still 30 fps, so
the renderer work is not finished.

---

## 4. The crash

### 4.1 Sequence in `fh1_009`

Frame 2400 is reported at `10:24:36.493`, then the game continues into a
car/garage-like scene. The log shows car assets being opened
(`media\brakes\...`, `media\cars\GMC_YukonXL_01.zip`,
`media\cars\MIT_LancerEVOVIGSR_99.zip`, engine soundbanks) and many graphics
pipelines being created.

At `10:24:40.351`:

```text
[error] ExecutePacketType3 overflow (read count 00000004, packet count 00010000)
[error] overflow header=FFFFFFF0 opcode=7F read=6FBC write=6FC0 capacity=20000
```

The ring dump:

```text
overflow ring @6F9C: 7FFF7FFF 00000000 00000000 FFFFFFF0 FFFFE3B0 FFFFE3B0 00000000 FFFFFFF0
overflow ring @6FBC: FFFFFFF0 7FFF7FFF 7FFF7FFF 00000000 00000000 FFFFFFF0 FFFFE3B0 FFFFE3B0
overflow ring @6FDC: 00000000 FFFFFFF0 FFFFFFF0 7FFF7FFF 7FFF7FFF 00000000 00000000 FFFFFFF0
overflow ring @6FFC: FFFFE3B0 FFFFE3B0 00000000 FFFFFFF0 FFFFFFF0 7FFF7FFF 7FFF7FFF 00000000
```

Then:

```text
[error] **** PRIMARY RINGBUFFER: Failed to execute packet.
[error] primary buffer read_index=1BED write_index=1BF0 read=6FBC write=6FC0 size=20000
```

At `10:24:45.362`:

```text
[error] Unhandled guest access violation: read of guest 0x00000014
        (host 0x0000006249DCC014) on thread 0xF8001344
```

### 4.2 Guest fault details

`rex_crash.log` maps the host PC back into the recompiled guest image:

```text
pc 0x0000005e67685f9c = imagen+0x2876f9c
lr 0x0000005e6822cd64 = imagen+0x341dd64
far dentro de la memoria del invitado: 0x00000014
x1  0x0000006249dcc000
x3  0x0000000000000014
```

`addr2line` on the unstripped `fh1` gives:

```text
0x2876f9c -> sub_830034A0+0x4c
0x341dd64 -> sub_83006440+0x1b4
```

The faulting instruction is:

```asm
2876f9c: ldr w3, [x1, w3, uxtw]   ; read from x1 + w3
```

with `x1 = 0x6249dcc000` and `w3 = 0x14`, so the read is `0x6249dcc014`, which
the host identifies as guest address `0x14`.

The value came from the preceding block:

```asm
2876f74: ldr w3, [x1, w3, uxtw]   ; w3 = field at x1 + w2 + 0x190
2876f80: rev w3, w3               ; byte swap -> 0xFFFFFFF0
2876f84: add w3, w3, #0x24        ; 0xFFFFFFF0 + 0x24 = 0x14
2876f9c: ldr w3, [x1, w3, uxtw]   ; fault at guest 0x14
```

In other words, a guest structure contained the post-swap value `0xFFFFFFF0`
where a valid pointer was expected. Adding `0x24` wrapped to `0x14`, and the
next dereference faulted. `sub_830034A0` is a recompiled guest routine, not a
host Vulkan function.

### 4.3 Same crash in the old build

`fh1_007.log` (old build) contains:

```text
ExecutePacketType3 overflow (read count 00000194, packet count 00010000)
overflow header=FFFFFFF0 opcode=7F read=3B90 write=3D24 capacity=20000
**** PRIMARY RINGBUFFER: Failed to execute packet.
...
Unhandled guest access violation: read of guest 0x00000014
  (host 0x00000025AAA0E014) on thread 0xF8001348
```

The old run's exact host PC is not preserved in the current `rex_crash.log`
(the live log only keeps the latest crash set), but the old `fh1_007.log`
shows the same ring failure and the same guest `0x14` fault. A crash entry
saved in the trash from an earlier run also contains a far-`0x14` fault in the
same recompiled neighborhood (`imagen+0x2876e5c`). The exact PC differs by a
few hundred bytes from the new `sub_830034A0+0x4c` fault, which is expected
when the same bug is reached through a slightly different code path or build.
The matching ring failure and guest address are the decisive evidence that the
2026-10-23 changes did not introduce the crash.

### 4.4 Not a Vulkan device loss

The GPU profile reports `0 dropped` frames and there is no
`VK_ERROR_DEVICE_LOST` or `device lost` message. The host does not abort on the
ring failure; `ExecutePrimaryBuffer` logs the error, breaks out of the packet
loop, calls `OnPrimaryBufferEnd`, and returns normally. The guest then continues
with a command stream that the host has only partially consumed, and faults a
few seconds later.

The ring failure is therefore the last observable host-side event before the
guest fault. It is not a GPU crash; it is a command-stream desynchronisation.

---

## 5. Ringbuffer analysis

### 5.1 What the numbers mean

- `read=6FBC` and `write=6FC0` are **dword indexes**, not bytes.
- The primary ring capacity is `0x20000` dwords.
- `read_count()` (`rex/memory/ring_buffer.h:41`) returns
  `(write - read) mod capacity`, here `4` bytes.
- The packet header at `0x6FBC` is `0xFFFFFFF0`. Decoded as a type-3 packet:
  - type = `0xFFFFFFF0 >> 30` = 3;
  - opcode = `(0xFFFFFFF0 >> 8) & 0x7F` = `0x7F`;
  - payload dwords = `((0xFFFFFFF0 >> 16) & 0x3FFF) + 1` = `0x4000`;
  - payload bytes = `0x10000`.
- The host therefore sees a valid-looking type-3 header claiming 64 KiB of
  payload, but only 4 bytes are published. It rejects the packet.

The ring dump around the read pointer repeats patterns such as:

```text
FFFFFFF0 7FFF7FFF 7FFF7FFF 00000000 00000000 FFFFFFF0 FFFFE3B0 FFFFE3B0
```

That is not a normal command list. It is consistent with the "previous
contents" of the ring, including old packet headers and payload bytes.

### 5.2 What happens after the rejection

`ExecutePacketType3` returns `false` (`command_processor.cpp:867-877`).
`ExecutePrimaryBuffer` logs the failure and breaks (`:704-713`), then returns
`write_index` (`:730`). The caller assigns that to `read_ptr_index_`.

So on the failure path the host:

1. consumes the 4 bytes of the bogus header;
2. discards the remaining `0xFFFC` bytes of the declared packet;
3. publishes a read pointer that is now misaligned with the guest's packet
   stream;
4. continues with the next batch as if the ring were at a packet boundary.

Any payload that the guest writes after `0x6FC0` is then interpreted as packet
headers. That is exactly the kind of desync that ends in a guest null-pointer
walk.

### 5.3 There was no earlier `Type-3 desync`

`fh1_009.log` contains no `Type-3 desync` messages before the overflow. There is
also no `CDCDCDCD` warning. So the first visible failure is the bogus header
itself, not a handler that consumed the wrong number of words from an otherwise
valid packet.

The host's type-3 handler now validates its own consumption
(`command_processor.cpp:847-865`), but type-0 and type-1 packets do not have an
equivalent check. A one-word error in a type-0/type-1 packet would not be
reported and could produce this symptom. That is a secondary hypothesis, not
the leading one.

### 5.4 The leading hypothesis: a stale or premature `CP_RB_WPTR`

The source already contains a comment for this exact symptom
(`graphics_system.cpp:269-276`):

```text
The Switch is ARM (weakly ordered) while the guest code was compiled for
PowerPC, whose sync/lwsync/eieio are currently emitted as no-ops by the
codegen (it assumes x86 ordering). Guest MMIO stores such as CP_RB_WPTR
are the hand-off to the GPU worker thread: without a release fence the
guest's command-buffer stores may still be in flight when the worker reads
the ring, so it sees the previous contents (a repeating 40-byte template).
Order all prior guest stores before the register write that publishes them.

std::atomic_thread_fence(std::memory_order_seq_cst);
```

The ring pattern in these crashes is exactly the "previous contents" template
described there. The fence exists, so either:

1. the fence is not strong enough for this hand-off (`dmb ish` vs `dsb ish`,
   or the worker still observes the write pointer before the ring payload);
2. the `CP_RB_WPTR` store takes a path that does not go through
   `GraphicsSystem::WriteRegister`, so the fence is not applied;
3. the guest itself publishes the write pointer before the payload is complete
   (because its `sync`/`lwsync` are no-ops, and the codegen or CPU reorders the
   stores across the MMIO call);
4. the ring was reset and the host retained an old read pointer, so the "old
   contents" are not actually a partial new packet.

The `write=6FC0` value is only 4 bytes ahead of `read=6FBC`. That strongly
suggests the worker is processing a write pointer that does **not** include the
full packet it is trying to read. If the guest had published the complete
packet, the write pointer would be at least `0x6FBC + 0x10000` (mod capacity).
It is not. So the host is reading a packet before the guest has published its
payload, or the write pointer it read is stale/partial.

### 5.5 Why the other changes are not the cause

- **ZCULL / `TRANSFER_DST`:** the old `fh1_007` build has the same crash without
  this change. ZCULL only changes Vulkan depth-image usage; it does not write
  the PM4 ring.
- **Full-clear tracking:** old `fh1_007` has the same crash and does not have
  the counter.
- **Occlusion queries:** old `fh1_007` has the same crash. Disabling occlusion
  can change how many draws the game submits, but the old run crashes without
  that change.
- **`vulkan_submit_on_primary_buffer_end`:** old `fh1_007` has the same crash.
  The ring overflow happens in the command processor before the submit path.
- **Depth image usage / `CreateSurfaceImage`:** no code path here touches the
  primary ring or the guest's write-pointer publication.

The changes may affect **when** the crash happens (more draws, different
submission timing), but not **whether** the underlying desync exists.

---

## 6. Recommended fix

There are two layers: stop corrupting the stream on overflow, and then fix the
publication race that creates the overflow.

### 6.1 Do not consume an incomplete packet

Minimal, low-risk change in `ExecutePrimaryBuffer`:

- On `ExecutePacket` failure, do **not** return `write_index`.
- Restore the reader to the start of the failed packet and return that index.
- Make the worker wait on `write_ptr_index_event_` until the write pointer
  changes, then retry.
- Add a bounded retry/timeout and a fallback for genuinely bad packets, so a
  malformed packet cannot deadlock the GPU thread forever.

Conceptually:

```cpp
const uint32_t packet_start = reader.read_offset() / sizeof(uint32_t);
if (!ExecutePacket(&reader)) {
  reader.set_read_offset(packet_start * sizeof(uint32_t));
  return packet_start;  // do not consume; wait for more data
}
```

The worker loop must treat "no progress but read != write" as a reason to wait,
not as a reason to spin. A short wait (or `MaybeYield`) is enough; the guest is
on another core.

This does not fix the root cause, but it prevents the host from interpreting
the rest of a packet as headers. If the guest later publishes the missing
payload, the retry can succeed. If the packet is truly garbage, the timeout
fallback should skip it explicitly and log a ring dump.

### 6.2 Strengthen the write-pointer hand-off

- Verify every `CP_RB_WPTR` write goes through `GraphicsSystem::WriteRegister`.
  Add a temporary log if needed.
- Use a release store for `write_ptr_index_` and an acquire load in the worker
  (`std::memory_order_release` / `std::memory_order_acquire`) instead of relying
  only on the surrounding fence.
- Test a stronger barrier (`dsb ish` / `__sync_synchronize`) in
  `WriteRegister` before `UpdateWritePointer`. If that changes the failure,
  the diagnosis is confirmed.
- Ensure the event `Set()` happens after the release store, and that the worker
  does not use a write pointer loaded before the wait.

### 6.3 Add diagnostics

At the first overflow, log enough to distinguish stale-WPTR from bad-packet:

- the last 8 values written to `write_ptr_index_` with timestamps;
- the current `read_ptr_index_` and `write_ptr_index_`;
- whether `write_ptr_index_` changed while the worker was processing;
- the ring window before and after the read pointer;
- the last 16 type-3 headers and their opcodes/counts.

This is more valuable than more performance profiling: the crash is the blocker.

### 6.4 Re-test occlusion

Run the same route with:

```toml
occlusion_query_enable = true
```

and compare `draw_stencil`, `draw CPU`, frame ms, and whether the crash moves.
If the late-scene draw count collapses, keep occlusion enabled. If the crash
remains, it is independent of draw count.

---

## 7. Verification plan

1. Build the overflow/retry fix.
2. Run the same route to frame 2400 and into the car/garage scene.
3. Confirm:
   - no `ExecutePacketType3 overflow`;
   - no `Unhandled guest access violation`;
   - no `Type-3 desync`;
   - ZCULL planes still present;
   - `transfer_skipped_full_clear` still non-zero.
4. A/B `occlusion_query_enable` on/off with the same route.
5. A/B `vulkan_submit_on_primary_buffer_end` on/off with the same route.
6. Only after the crash is gone, continue with the renderer targets
   (transfers/resolves/texture CPU).

---

## 8. Open questions

- Is the repeating pattern at the read pointer the old ring template, or a
  partially written new packet?
- Does the guest publish `CP_RB_WPTR` per packet, or per batch? The 4-byte
  difference suggests per-packet publication.
- Do all `CP_RB_WPTR` writes use `GraphicsSystem::WriteRegister`? The comment
  says yes, but the crash suggests the fence is not sufficient.
- Are guest `sync`/`lwsync` really no-ops in this build? If so, the ring
  publication relies entirely on the host-side fence.
- Is the `0xFFFFFFF0` in the guest structure the same value as the ring header,
  or a coincidence? The value and the crash timing suggest a shared corruption,
  but this is not proven.
- Could the guest be resetting the ring while the host still holds an old read
  pointer? The `read=6FBC/write=6FC0` pair is consistent with a stale pointer,
  but a ring dump of the previous WPTR values would settle it.

---

## Appendix A - exact failure excerpts

`fh1_009.log`:

```text
[2053-06-30 10:24:36.493] FH1 native executor (Vulkan) frame=2400
  draws=376052 resolves=71966 surfaces=38
  stats={... transfer=67841, transfer_skipped_full_clear=18103,
         transfer_stencil_skipped=21891, ...}
[2053-06-30 10:24:36.496] gpu ms/frame over 601 frames (0 dropped):
  frame 115.159 transfers 49.875 resolves 41.258 clears 0.580
  texture_loads 4.499
[2053-06-30 10:24:40.351] ExecutePacketType3 overflow
  (read count 00000004, packet count 00010000)
[2053-06-30 10:24:40.356] overflow header=FFFFFFF0 opcode=7F
  read=6FBC write=6FC0 capacity=20000
[2053-06-30 10:24:40.377] **** PRIMARY RINGBUFFER: Failed to execute packet.
[2053-06-30 10:24:40.381] primary buffer read_index=1BED write_index=1BF0
  read=6FBC write=6FC0 size=20000
[2053-06-30 10:24:45.362] Unhandled guest access violation:
  read of guest 0x00000014 (host 0x0000006249DCC014)
  on thread 0xF8001344
```

`fh1_007.log` (old build):

```text
[2053-06-30 07:22:31.014] ExecutePacketType3 overflow
  (read count 00000194, packet count 00010000)
[2053-06-30 07:22:31.016] overflow header=FFFFFFF0 opcode=7F
  read=3B90 write=3D24 capacity=20000
[2053-06-30 07:22:31.035] **** PRIMARY RINGBUFFER: Failed to execute packet.
[2053-06-30 07:22:36.173] Unhandled guest access violation:
  read of guest 0x00000014 (host 0x00000025AAA0E014)
  on thread 0xF8001348
```

`rex_crash.log` (new run):

```text
pc 0x0000005e67685f9c = imagen+0x2876f9c
lr 0x0000005e6822cd64 = imagen+0x341dd64
far dentro de la memoria del invitado: 0x00000014
x1  0x0000006249dcc000
x3  0x0000000000000014
```

`addr2line`:

```text
0x2876f9c -> sub_830034A0+0x4c
0x341dd64 -> sub_83006440+0x1b4
```

---

## Appendix B - source references

| Area | File / line |
| --- | --- |
| ZCULL depth usage fix | `port/switch/sdk/src/graphics/vulkan/fh1_native_executor.cpp:730` |
| Depth growth image still `TRANSFER_DST` | `fh1_native_executor.cpp:836` |
| Full-clear state | `fh1_native_executor.h:151`, `fh1_native_executor.cpp:1219,1824,1960,2037` |
| Primary ring execution | `port/switch/sdk/src/graphics/command_processor.cpp:660` |
| Failure path consumes `write_index` | `command_processor.cpp:704-730` |
| Type-3 overflow check | `command_processor.cpp:867-877` |
| Type-3 consumption validation | `command_processor.cpp:847-865` |
| Ring read count | `port/switch/sdk/include/rex/memory/ring_buffer.h:41` |
| Ring advance | `port/switch/sdk/src/core/ring_buffer.cpp:22` |
| `CP_RB_WPTR` hand-off fence | `port/switch/sdk/src/graphics/graphics_system.cpp:266-283` |
| `CP_RB_WPTR` case | `graphics_system.cpp:279` |
| Occlusion fallback | `port/switch/sdk/src/graphics/command_processor.cpp:1422` |
| Occlusion cvar | `port/switch/sdk/src/graphics/command_processor.cpp:49` |
| Fake sample count cvar | `port/switch/sdk/src/graphics/command_processor.cpp:76` |
| Vulkan submit cvar | `port/switch/sdk/src/graphics/vulkan/command_processor.cpp:167` |

---

## Appendix C - build and log commands

Build:

```sh
/home/kaze/PinyonShift-NX/pinyon-shift/.local/toolchain/ninja-1.13.2-linux/ninja \
  -C /home/kaze/PinyonShift-NX/port/switch/app/out/sw fh1 -j4
```

Hash:

```sh
sha256sum /home/kaze/PinyonShift-NX/port/switch/app/out/sw/fh1.nro
```

Copy to SD (MTP):

```sh
gio copy /path/to/fh1.nro \
  "/run/user/1000/gvfs/mtp:host=Nintendo_Nintendo_Switch_XAW00000000000/SD Card/switch/fh1/fh1.nro"
```

Inspect the new run:

```sh
grep -n "ZCULL: plano\|transfer_skipped_full_clear\|gpu ms/frame over\|ExecutePacketType3 overflow\|Unhandled guest" \
  /home/kaze/PinyonShift-NX/logs/fh1_009.log
```

Map a crash PC:

```sh
addr2line -f -C -e /home/kaze/PinyonShift-NX/port/switch/app/out/sw/fh1 \
  0x2876f9c 0x341dd64
```

---

## Appendix D - fix attempt 1 (2026-10-23 07:47)

Implemented the non-consuming ring-stall fix from section 6.1.

Code changes:

- `CommandProcessor::ExecutePrimaryBuffer` now returns
  `PrimaryBufferResult { read_index, incomplete }`.
- Before executing a packet it peeks at the header and computes the declared
  packet size (type 0/3: header + payload count, type 1: 3 dwords, type 2: 1
  dword). If the published write pointer does not cover the whole packet, the
  packet is left unconsumed and `incomplete = true` is returned.
- The worker now waits on `write_ptr_index_event_` for `CP_RB_WPTR` to move
  instead of retrying in a busy loop.
- A 5 s stall fallback logs a ring dump and resynchronises to the published
  write pointer, so a permanently malformed packet cannot deadlock the GPU
  thread.
- A packet whose payload is complete but whose handler returns false (for
  example an unimplemented opcode) is skipped explicitly with a ring dump,
  instead of stalling or corrupting the following packets.
- `ExecutePacketType1` now checks that two payload dwords are published before
  reading them.
- `OnPrimaryBufferEnd` is no longer called for an incomplete batch.

Build and deployment:

```text
fh1.nro SHA-256:
70a7a1d5a0562e5ee11df1856f7f0e313dd92cda81cb896351493e9ae2ae97f0
size: 108,796,101 bytes
deployed: port/switch/sd/switch/fh1/fh1.nro
```

Expected new log lines if the race is hit:

```text
**** PRIMARY RINGBUFFER: incomplete packet at ...
... waiting for CP_RB_WPTR
PRIMARY RINGBUFFER: CP_RB_WPTR stuck at ... for 5s; resynchronizing
**** PRIMARY RINGBUFFER: failed complete packet at ...; skipping it
```

Test: run the same route to frame 2400 and into the garage. Primary success
criteria are no `ExecutePacketType3 overflow`, no `Type-3 desync`, and no
`Unhandled guest access violation`. If the incomplete-packet log appears but
the run continues, the wait path worked; if the 5 s resynchronisation log
appears, capture the following ring dump.
