# Scaled texture binding ownership

Issue [#628](https://github.com/arcanite24/pinyon-shift/issues/628) reports world
texture corruption after saving decals or opening Design Creator with an
existing design. Entering the editor with a stock car clears it. Investigation
found a reproducible ownership defect in the shared texture binding memo.

## The cache defect

The six fetch-constant words describe a guest texture. They do not say whether
its bytes currently belong to the ordinary shared-memory buffer or the scaled
resolve buffer. `FindOrCreateTexture` makes that choice from the resolve-page
map and includes `scaled_resolve` in the actual host texture key.

The binding memo stored the selected host texture pointer alongside the fetch
words. After a GPU resolve or CPU write, selective binding invalidation cleared
the affected binding, but retained the memo. Repeating the same fetch words
then recovered the old pointer without checking the current ownership map.
Consequently a CPU texture could keep reading the scaled buffer, or a resolved
texture could keep reading the ordinary buffer.

At scaled resolutions, a memo entry naming an outdated texture now goes
through `FindOrCreateTexture` again. Clean entries and the 1x path retain their
existing reuse. This does not flush texture contents, drop unrelated bindings,
or clear the whole cache per frame.

## Regression coverage

The SDK's `tests/unit/graphics/texture_cache_test.cpp` exercises the real shared
cache and memory watches with a backend that records no GPU commands. It keeps
the fetch constants unchanged while switching CPU → scaled resolve → CPU,
including consuming an invalidation while only another binding is requested.
It checks the selected host texture and verifies that an unrelated texture's
payload generation never changes.

On multivac (Windows x64, 2026-10-18), the standalone fixture fails two of its
14 assertions with the original cache: the resolved texture is still the
original unscaled object. With the patch all 14 assertions pass. The regression
also passes in the SDK unit suite built entirely from the worktree sources
(296 tests passed, four skipped, 2,436 assertions passed).

## Single-channel editor resolves

Entering Add Decals from a stock MX5 also exposed an unsupported native resolve:
`c0->t2/1x/s0`, followed by `c0->t2/4x/s6`, with destination register
`0x01000100`. These copy RGBA8 EDRAM into a tiled 8-bit unorm texture, including
the average of all four MSAA samples. The native planner rejected destination
format `k_8`, producing backend draw failures. This is an observed editor defect;
it alone does not explain corruption after saving a design.

The resolve shader now packs this format into one byte per texel, after sample
averaging, exponent bias, and channel swap. Atomic masked word updates preserve
the other three bytes while independent texel threads execute. Endianness
permutes the destination byte lane. The same tiled and scaled address formulas
apply with bytes-per-texel log2 set to zero. This path uses the ordinary texture
reload mechanism rather than the optional direct-to-32-bit-texture optimization.

Both DXBC and SPIR-V resolve variants were rebuilt using the SDK shader script's
compiler options. All 12 SPIR-V variants pass `spirv-val`. A unit regression
passes the observed destination register through the real resolve planner at
1x and 4x MSAA, checking support, byte size, destination extent, and base. With
both corrections the full SDK suite passes 297 tests (four skipped), with 2,452
assertions.

The first editor-entry ownership trace recorded 278,506 invalidation ranges,
of which 259,069 came from GPU writes, and 84 sampled texture reload attempts.
Four sampled identities had both ordinary and scaled host allocations, including
the 1280x720 front buffers. It contained no whole-512-MiB GPU invalidation.
Those observations establish alias activity, not which world texture becomes
corrupt after a saved design; that needs the acceptance checks below.

## Gameplay acceptance

The unit regression establishes the cache defect independently of menu timing.
Qualifying the complete issue additionally requires a private pinned save and
the following visual checks at both 1x and a scaled resolution:

1. Enter Paint Shop and Design Creator with a stock car, add decals, and save.
2. Exit to free roam; check the design, road surfaces, and roadside signs.
3. Travel away and return, then restart from a snapshot of the saved private
   state and check the same textures.
4. Re-enter Design Creator with the painted car and repeat the world checks.
5. Enter the editor with a stock car without adding a decal as a control.

Use `fh1_texture_reload_probe` to correlate texture allocation IDs, physical
base/mip ranges, scaled variants, and CPU/GPU invalidation reasons. A route
result marked `pass` proves that the script completed; its captures must also
show that it actually reached and saved in the editor.
