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

## World detail

What was found while looking for a draw distance setting (#421,
[FEATURE_BACKLOG.md](FEATURE_BACKLOG.md) FB-4). None of the data knobs
below gave a visible gain.

| Base | v4 | Name | What it is | Established by | Confidence |
| --- | --- | --- | --- | --- | --- |
| `sub_82D505C0` | — | track render settings | Serializes the per-track render settings that `media/tracks/<track>/TrackSettings.xml` sets, plain XML read in free roam. Field offsets: `GrassLODDist` +712, `GrassLODFadeRange` +716, `GrassMinNumShells` +720, `GrassFadeStartDistance` +728, `GrassFadeEndDistance` +732, `Crowds` +832, `CollidableDropDistance` +656, `wholeTrackLightmapRadius` +1248, `depthPassRadius` +1252, `screenAreaDistances` +1260, `Performance` +1378, `MipMapLodBiasModifier` +1404, besides lighting, tone map and wind fields. | Key strings mapped to the serializer's field arguments; a mod replacing the file logged `mod.file.override` in free roam. | Confirmed |
| `TrackSettings.xml` (Colorado) | same | no visible gain | Doubling the grass fade distances, the crowd LOD and sprite distances and `screenAreaDistances mainScene` changed nothing visible in free-roam views; the only differences were moving cars. | A/B captures of the same free-roam views from one seed. | Confirmed |
| `tracks\%s\Ribbon_%02d\*.pvs`, `PVSZLookup`, `CTrackPVSZoneResource`, `PVSZoneSpeeds.dat` | same | scenery visibility | Track scenery is culled through precomputed visibility (PVS) zones, not by a distance, so there is no draw distance value to raise for it. | Strings and class names in the executable. | Probable |
| `0x8207AA58` `draw_distance`, `sub_828C6E68` | — | map draw distance | Belongs to the map and minimap profiles (`MapProfileFullscreen.xml`, `MapProfileMinimap.xml`), not the 3D world. | String xref. | Probable |
| `0x820744F0` `CamFarClip` | — | camera far plane | Read by the camera functions `sub_8284DAE0`, `sub_8284CB30`, `sub_8284C5D0`, `sub_8284C410`. `camera.zip` sets only near planes (`CameraSettings.ini`), so the far plane is a code default. | String xref; reading the camera archive. | Probable |
| `0x8201BA00` `SLod.xml`, `sub_82548C20`, `sub_82548E78` | — | car shader settings | `cars/Shared.zip` `ShaderSettings/Slod.xml` (and `Tire/Slod.xml`): settings for the distant-car "super LOD" shader, not world LOD. | String xref; archive listing. | Confirmed |
| `sub_82D86268` | — | dynamic render settings | Constructor of the per-scenario render settings that `media/renderscenarios.zip` fills (`CDynamicRenderControl` entries: `FrameRate`, `TilingScenario`, car LOD, crowds, particles and more). Every scenario file is parsed into its own object at boot, through one XML reader archive (vtable `0x8222B154`, v4 `0x8223DEC4`). Each control's vtable holds a name getter, a serialize (a visitor binding attribute names to fields) and a reset. | Probe hooks on the visitors logged every read with the archive's vtable. | Confirmed |
| `sub_82D7E2A8` reset, `sub_82D7E1F8` visitor, `sub_82D7E290` name | `sub_82E404D0`, `sub_82E40420`, — | `CarLODTransDist` | Three floats (`near`, `far`, `veryfar`) at +168/+172/+176 of the render settings (control at +164); compiled defaults 15/25/50 m, the same as every race file. | Hooks on every writer: reset, constructor and XML visitor. | Confirmed |
| `sub_82D7E4B0` reset, `sub_82D7E2E8` constructor, `sub_82D7E390` visitor, `sub_82D7E498` name | `sub_82E406B0`, `sub_82E40510`, `sub_82E405B8`, — | `CarLODTransDistTraffic` | Six floats (`LOD2`..`LOD5`, `LOD4_closest`, `LOD5_closest`); defaults 15/25/50/100/20/80 m, and `Horizon_Race.xml` sets 22/40/75/100/30/80. | Same hooks. | Confirmed |
| `CarLODTransDist`, `CarLODTransDistTraffic` | same | no visible car LOD change | Scaling both tables by 0.01 at every writer left the cars' models unchanged, in free roam and in a race (`fh1-race-start-wait`, frames aligned within 5 % of pixels). They do not select the model LOD the player sees. | Deterministic A/B captures with the scale hooks (not kept). | Confirmed |
| `CarLODThresholds` | same | no visible change on the grid | Setting `lod1`, `lod2` and `count` to 0 in all 19 scenarios that set them left the race grid cars unchanged. An earlier probe on 2026-10-10 that saw `Horizon_Race.xml` change race cars was not reproduced and was probably run-to-run variance. | Member-replacing mod, A/B grid captures. | Confirmed for the grid view |
| `CarFocusLODMinMax min=0 max=0` | same | player car held at LOD0 | Seven scenarios clamp the focused car's LOD to 0, which is why the player's car never changes detail. | Reading the scenario files; the player car stayed identical in every probe. | Probable |
| `0x82237FE4` (`CCullingGroupTable`), `0x82243414` (`CTrackRenderModel`), `0x82243464` (`CTrackRenderModelInstance`), `0x82001474` (`CTrackSubModel`), `0x820016B4` (`CTrackModel`) | — | track class vtables | Found through their RTTI. The instance's methods are short thunks, so the LOD or cull decision is not in them. No executable string names a scenery LOD scale, bias or distance. | RTTI type descriptors and complete-object locators. | Confirmed |
| `sub_82DB8AE8` > `sub_82DC1CB0` > `sub_82D65608` | — | scene draw on the render thread | In free roam the render thread (guest `825A6320`) spends most of its busy time here, and below `sub_82D65608` only in draw submission (`sub_82440CF8`). The main thread (guest `8255AE10`, also `82C0C8C8`) walks the scene through `sub_82D4E2E0` > `sub_82D4DE30`, into `sub_82D46EF8` > `sub_82D3A528` and `sub_82D4DCC8` > `sub_82D43818` > `sub_82D41A30` next to the culling-group table's method: the next place to look for where a model LOD is chosen. | `pinyon_shift_thread_sampler` over every guest thread during a free-roam drive. | Probable |
| Xenia `4D5309C9` game patches | — | no LOD patch exists | Xenia Canary's FH1 patches cover motion blur, depth of field, shadows and hash checks; none raises LOD or draw distance. | Reading the patch file. | Confirmed |

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
