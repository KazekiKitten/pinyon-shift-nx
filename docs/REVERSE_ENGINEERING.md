# Reverse-engineering records

What we have learned about FH1 by reverse engineering, so later work can
build on it instead of finding it again (#448). Symbols and offsets that
mod code uses live in [`config/mod/fh1-symbols.toml`](../config/mod/fh1-symbols.toml)
(v4 in [`fh1-offsets-v4.toml`](../config/mod/fh1-offsets-v4.toml)); every
other finding gets a row here. Negative results count too.

Only our own analysis goes here: no disassembly listings, decompiled code
or game data ([LEGAL.md](LEGAL.md)).

Confidence: **confirmed** (shown directly), **probable** (strong indirect
evidence) or **guess**.

## Rendering

| Base | v4 | Name | What it is | Established by | Confidence |
| --- | --- | --- | --- | --- | --- |
| guest phys `1FCA6000`, 4 KB | — | scene luminance resolve | A 32x32 `k_32_FLOAT` resolve from a 1x `k_32_FLOAT` color target (`c14->t36`), resolved every frame in free roam. The game reads it at guest size, through a texture key that is not marked as a scaled resolve. If guest memory under it is stale, the screen is overexposed as if auto exposure sat at its daytime limit (#444). | Experiment: bisecting resolves at 2x on the `i444` route; writing the unscaled copy of only this resolve restored 1x brightness (mean 120.0 against 173.7). Texture-cache probes showed two 32x32 format-36 keys over it, one scaled and one not. | Confirmed that it drives exposure; probable that it is a luminance average. The address was seen on one seed only. |
| — | — | not the #444 cause | Ruled out for the morning overexposure at 2x: post effects (swap and present effects), MSAA (single sample), the GPU record thread, resolve-to-texture, EDRAM pass specialization, small copy views, texture band reloads. Guest CPU reads of resolved ranges (none), vertex fetches over scaled ranges (none), and unscaled textures over scaled ranges caught by the generic probe (none). | Experiment: one cvar or probe at a time on the `i444` route. | Confirmed |

The fix and its reasoning are in [DEVELOPMENT.md](DEVELOPMENT.md)
(guest-visible resolves).

## Radio

| Base | v4 | Name | What it is | Established by | Confidence |
| --- | --- | --- | --- | --- | --- |
| `media/audio/radio/RadioSystem.xml` | same | station list | Nine stations: `Radio1` Horizon Bass Arena, `Radio2` Horizon Pulse, `Radio3` Horizon Rocks (stereo music), `Radio4_Silent` (off), and the mono 3D location stations `Radio5_3d_PreRace`, `Radio6_3d_Autoshow`, `Radio7_3d_Workshop`, `Radio8_3d_Paintshop`, `Radio9_3d_Streetrace`. | Reading the file; station changes in game. | Confirmed |
| executable strings | — | selectable stations | The executable names the player-selectable stations itself: the `RadioN` names, `Radio4_Silent` for off, `ui\textures\horizon\hud\radio\radio1..3.xds` and the option strings `IDS_RadioStation_Option_1/2/3/Off`. Adding a fourth selectable station therefore needs guest code changes, not only data (#453). | Strings in the executable. | Confirmed that the names are there; probable that the selectable count is fixed in code. |
| `Horizon.zip/Hud/Radio/RS_BassArena.xds`, `RS_Pulse.xds`, `RS_2Eleven.xds` | same | station popup logos | The logos shown at the right of the HUD when the station changes: 210x100 DXT5 (`k_DXT4_5_AS_16_16_16_16`), tiled, 8-in-16, one level. `RS_2Eleven` is Horizon Rocks. `RS_Off.xds` (32x32) is the radio-off icon. | Experiment: a re-encoded `RS_BassArena` showed in the Radio1 popup (#445); decoding the textures. | Confirmed |
| `Horizon.zip/Hud/Radio/Radio1-3.xds` | same | placeholder logos | 64x32 DXT1 images that only read "Radio N". Their paths are the ones in the executable, but the popup shows the `RS_*` textures. | Decoding the textures; route captures. | Guess: unused in normal play |
| `MyProfile.str` `0xA29E`, `0xA31E`, `0xA39E` | same | station names | HORIZON BASS ARENA, HORIZON PULSE and HORIZON ROCKS, the RADIO STATION option's values (`0x7693` is the row's label). | Reading the string tables. | Confirmed in the tables; probable on the option screen (not seen on screen) |
| `Tips.str` `0x0B3A`/`0xE484`, `0xF203`/`0x0063`, `0x9730`/`0x94AE` | same | station tips | The loading tips' title and text for Bass Arena, Pulse and Rocks. `Livery_Decals.str` `0x6AF9`, `0x328D` and `0xAEF9` name the station decals. | Reading the string tables. | Confirmed |
| `Radio_Music.fsb` | same | music bank | The FSB4 layout, sync points and the info file. | See [FEATURE_BACKLOG.md](FEATURE_BACKLOG.md) FB-1.3. | Confirmed |
