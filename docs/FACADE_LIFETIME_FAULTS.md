# Facade lifetime faults (#556 and #674)

These reports have different demonstrated failure paths. They do not justify
ignoring null writes or disabling speech/media jobs.

## Android stack reuse (#556)

The Pixel 3 XL report names Android 13 with Linux 4.9.337. The parent thread
faults writing guest `0x70830000`, with LR `0x881ED538`, in bionic `memset`.
`0x881ED4F0` is XMediaFacade's thread-creation wrapper; that return address
follows its `ExCreateThread` import. Both addresses are unchanged in v4
(normalized function match against the extracted base and v4 images).
This is thread creation on the parent, not a fault in a running child fiber.

`XThread::AllocateStack` reserves and commits a guest range, fills it, then
protects its guards. Reused stack ranges can still have inaccessible guards
from their previous owner. The POSIX allocator used `MAP_FIXED_NOREPLACE`
and accepted any successful `mmap` result. Linux before 4.17 can ignore that
flag and return a different address when the requested range already exists;
see [mmap(2)](https://man7.org/linux/man-pages/man2/mmap.2.html).
That leaves the requested guard inaccessible and leaks the relocated mapping.
It explains how stack initialization can fault despite successful allocation.

The allocator now rejects relocated results, unmaps them, and uses the same
existing-reservation commit path as an `EEXIST` result. Reserve-only
collisions still fail. No existing data is replaced and no guard is relaxed
outside the requested commit range. The SDK's `memory_posix_tests` intercepts
only its local `mmap` calls and strips the flag to reproduce the old-kernel
contract on a current kernel. It checks guard reuse, preserved data, no leaked
mapping, reserve-only collisions, and ordinary current-kernel commits.

The production backend passed 23 assertions on 4 KB WSL Linux. A separate
NDK-built ARM64 probe ran on an Odin 2 Portal (4 KB pages, Linux 5.15.123)
with `MAP_FIXED_NOREPLACE` deliberately ignored: the original backend
returned the wrong mapping, while the patched backend committed and wrote
the original guard. Only temporary executables were deployed; the installed
APK, settings and save were unchanged, and the probe files were removed.

Validation still needs a current Pixel 3 XL launch on the reporter's kernel.
The GPU budget warning is separate evidence and does not establish OOM as the
cause of this access violation.

## Windows unload/reload (#674)

The 0.6.0 report faults writing guest `0x00000006`, LR `0x82CC1B60`, after
XMediaFacade reload and SpeechFacade unload. Static analysis places that LR
after the virtual allocation call in `0x82CC1B10`. The allocator is selected
by the current guest thread ID through `0x82CBC390` and registry lookup
`0x82CBC348`; its registry starts at `0x8349F978`, with the selection gate
at `0x8349FDB4`. It is not a demonstrated speech callback at that LR.

Verified base-to-v4 mappings, using function/context and paired data loads:

| Base | v4 | Role |
| --- | --- | --- |
| `0x82CC1B10` | `0x82D83590` | allocation entry |
| `0x82CC1B60` | `0x82D835E0` | return from override allocation |
| `0x82CC1B58` | `0x82D835D8` | diagnostic hook before the override call |
| `0x82CBC390` | `0x82D7DE88` | current thread's allocation override |
| `0x82CBC348` | `0x82D7DE40` | registry search by guest thread ID |
| `0x8349F978` | `0x835950C8` | registry entries (ID, object pairs) |
| `0x8349FDB4` | `0x83595504` | override selection gate |

The LANGUAGE row saves `user_language` and `user_country` to the private
state's configuration and requires a process restart. It does not update the
live cvars or cancel speech work. The five settings events in the report
therefore do not prove language asset reload caused the crash.

`config/render-tests/fh1-facade-transitions.fh1test` exercises free roam,
five actual PROFILE/LANGUAGE changes, return to title, reentry, and another
return to title. Run through `tools/run-fh1-render-test.py` with pinned seed
`appdata-2026-09-27` and `--include-opening-movies`. Its expectation checks
ordered load/unload pairs for both facades and the five settings events;
survival without reaching the transition cannot pass. The runner copies the
seed into a private per-run state.

The route also enables `PINYON_SHIFT_FACADE_LIFETIME_TRACE`. Immediately
before the override call, `facade.allocation_override` records the guest
thread ID, object, target, size and attributes when the object/target changes
or the request is at least 1 MiB. It reads only the registers already prepared
for the call, changes no guest state, and is off outside this diagnostic.

The allocation target, object's ownership and faulting instruction still need
live evidence or the matching local crash dump. The uploaded diagnostics omit
the dump and contain no reproduction steps. A null-write suppression or a
speculative cancellation hook would hide this missing contract.

On multivac (Ryzen 7 5800X, RTX 4080), the existing baseline binary completed this
two-cycle route from the pinned seed without an access violation: five
LANGUAGE events, two speech loads/unloads and three media loads/two unloads.
Its embedded provenance reports `80f93d1+dirty` with SDK `773539d`; this
qualifies the route's reachability, not this branch or the original
884-second crash.
