# Linux and Steam Deck

Pinyon Shift builds and runs natively on x86-64 Linux, Steam Deck included.
Nothing runs through Proton or Wine. The setup is the same as on Windows: you
choose your own disc image, and the launcher verifies it, builds the game on
your machine and starts it.

## Steam Deck

You need your ISO of the USA retail disc (`MS-2505`), about 45 GB free on the
internal drive or a microSD card, and a charger: the first build takes
about 35 minutes and keeps the Deck busy throughout.

1. Hold the power button, choose **Switch to Desktop**.
2. Copy your ISO onto the Deck, for example from a USB drive or a microSD
   card, or over the network. Any folder works; **Downloads** is fine.
3. Open Firefox, download `PinyonShift-Launcher-linux-x86_64.tar.gz` from the
   [latest release](https://github.com/arcanite24/pinyon-shift/releases/latest)
   and verify the SHA-256 listed there.
4. In Dolphin, right-click the download and choose **Extract → Extract archive
   here**. Open the new `PinyonShift` folder and double-click
   `PinyonShiftLauncher`.
5. Choose **Choose disc image** and select your ISO, or drop it onto the
   launcher. Confirm ownership and choose **Verify and build**.
6. When the launcher says **Ready to drive**, choose **Add to Steam**. Steam
   restarts to pick up the entry and its artwork.
7. Double-click **Return to Gaming Mode** on the desktop. Pinyon Shift is in
   your library under **Non-Steam**. Start it from there from now on.

The launcher installs everything under `~/.local/share/PinyonShift`. Nothing
else on the Deck is changed apart from the Steam shortcut and an entry in the
applications menu, and SteamOS's read-only system needs no unlocking: no
password, no `pacman`, no developer mode.

### Playing on the Deck

- The built-in controls work as an Xbox 360 pad through Steam Input. Open the
  game's settings from the pause menu (SETTINGS), or anywhere by pressing
  View and Menu together (BACK + START, changeable under CONTROLS >
  CONTROLLER BUTTONS > SETTINGS MENU).
- **F6 > GRAPHICS > SCENE SHADING > COARSE** shades the scene once per 2 × 2
  pixels: a little softer, and about 8 % of the GPU's frame saved on the
  Deck.
- In our tests the race and free roam hold 60 fps at 1x (1280 × 720) under the
  Deck's default 15 W limit.
- **Leave Manual GPU Clock off** in the Quick Access menu's Performance
  settings. With it on, Steam can pin the GPU at 200 MHz, and the game drops
  to about 10 fps while the GPU reports full load at under 1 W.

## Linux PCs

Requirements:

- An x86-64 CPU with SSE4.1. The build uses x86-64-v3 (AVX2, FMA3, BMI2,
  MOVBE) when the CPU has it, as the Steam Deck's does.
- A Vulkan 1.3 driver: Mesa's RADV on AMD (Mesa 23 or newer), or NVIDIA's
  proprietary driver. Intel and NVIDIA on Linux are not qualified yet.
- glibc 2.31 or newer, `python3` 3.9 or newer, `git`, and GLib. Every current
  desktop distribution has them.
- About 45 GB free for the first build: the pinned compiler and the Steam
  Runtime SDK the game is built against take about 15 GB of it.

Download `PinyonShift-Launcher-linux-x86_64.tar.gz`, extract it and run
`PinyonShift/PinyonShiftLauncher`, then follow the Deck steps from step 5.
**Add to Steam** is optional on a PC; the launcher also adds Pinyon Shift to
your applications menu.

The game binary is built against the Steam Runtime 3 (sniper) SDK with a
pinned LLVM, so builds are reproducible and do not depend on your
distribution's compilers or libraries.

## From a terminal

The launcher runs these commands. In an extracted source tree or a repository
checkout:

```bash
python3 tools/pinyon.py setup --iso ~/Downloads/forza-horizon.iso
python3 tools/pinyon.py launch
python3 tools/pinyon.py shortcuts add
```

`setup` downloads its pinned, SHA-256 checked build tools into
`.local/toolchain`, reads the disc image directly (no `extract-xiso` or loop
mounts), checks every file against the supported dump and builds. Run
`setup --build-only` to rebuild after an update, and `shortcuts add
--no-steam` for only the applications menu entry. `shortcuts remove` undoes
both.

### Build options

- **CPU baseline.** Setup builds for the CPU it runs on: x86-64-v3 when
  `/proc/cpuinfo` lists `avx2 bmi1 bmi2 fma movbe f16c abm` (Haswell, Zen
  and later, the Steam Deck included), otherwise the FMA3 variant or
  SSE4.1. Set `PINYON_SHIFT_CPU_BASELINE=sse4.1` (or `fma`, `v3`) before
  `setup --build-only` to choose one, for example for a build that will be
  copied to an older PC. A build started on a CPU without its baseline stops
  with a message instead of crashing.
- **Code model.** Linux x86-64 builds use the small code model with linker
  relaxation (`REXGLUE_X86_64_CODE_MODEL=small`, the default). `large`
  (`-mcmodel=large -Wl,--no-relax`) is still accepted at configure time; it
  makes every call register-indirect.
- **Thread placement.** `linux_thread_cores` (default `auto`) pins threads by
  name. `auto` applies the layout measured on the Steam Deck when it detects a
  Deck (LCD or OLED) and does nothing on other PCs; the runtime log says
  which. `off` leaves every thread to the scheduler, and entries such as
  `GPU_Commands=4;*=5,7` set a layout of your own, as `android_thread_cores`
  does on Android. It can be changed while the game runs.
- **Building for a Deck on another PC** (the developer loop: WSL or a Linux
  PC, then `python3 tools/pinyon.py deck install`): configure with
  `cmake --preset linux-amd64-v3`, the Deck's x86-64-v3 variant, since a PC
  build cannot see the Deck's CPU. `deck install` copies
  `out/build/linux-amd64-v3` by default and falls back to the SSE4.1
  `linux-amd64-release` build with a note; `--build-directory` picks any
  other.

## Where things live

```text
~/.local/share/PinyonShift/source/<version>/   source, tools, game files, build
  .local/preview/user/                         saves
  .local/preview/                              settings, game logs, crash reports
  .local/logs/                                 setup logs
```

`PINYON_SHIFT_INSTALL_ROOT` moves the install elsewhere, for example to a
microSD card under `/run/media/`.

## Troubleshooting

- **Setup failed.** The launcher names the step and the log. The same report
  is in `.local/logs/setup-error.json`; attach it when you file an issue.
- **Very low frame rate on the Deck.** Check Manual GPU Clock, above.
- **The game does not appear in Game Mode.** Choose **Add to Steam** again
  while Steam is running; it rewrites the entry and restarts Steam. A backup
  of Steam's previous shortcuts is kept next to them as
  `shortcuts.vdf.pinyon-backup`.

## Uninstalling

1. Remove the shortcut in Steam, or run `python3 tools/pinyon.py shortcuts
   remove` in the install's source folder to remove it and the menu entry.
2. Copy your saves out of `.local/preview/user` if you want to keep them.
3. Delete `~/.local/share/PinyonShift`.

## Support status

| System | Status |
| --- | --- |
| Steam Deck LCD, SteamOS 3.7 | Builds and plays; 60 fps at 1x |
| Ubuntu 24.04 (WSL) | Release archive to a built game in 20 minutes; Add to Steam writes the shortcut and art; runs with a null GPU |
| Arch Linux (container, libxml2 2.15) | The pinned toolchain configures and links with setup's `ld.lld` wrapper (#472); a full build not run |
| Other distributions, NVIDIA, Intel | Not tested yet |

Work still open, such as DLC import and the title update build on Linux, is
tracked in the [Linux and Steam Deck backlog](LINUX_PORT_BACKLOG.md).
