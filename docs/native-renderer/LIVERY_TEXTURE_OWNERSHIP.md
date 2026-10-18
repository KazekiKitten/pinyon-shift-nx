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
