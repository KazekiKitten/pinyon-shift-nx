---
title: Systems and leftovers
section: Reverse engineering
order: 14
description: Forza Horizon's developer launch options and how to set them, debug features left in the retail build, the online services the game still calls, leftover modes and hardware support, and gameplay systems such as game control, race statistics and rewind.
---

# Systems and leftovers

The retail executable still contains much of the developers' tooling. About 300 **launch options** (`nohud`, `skiptutorials`, `numaicars`, `mainthread30fps` and others) are parsed into one options object, but the retail build never receives a command line, so none of them is set unless something writes the object directly. Debug menus, test tracks, telemetry pages, split-screen and linked-console code survive too; most of it cannot be reached.

The options object is a static singleton, so its flags are bytes at fixed addresses. A mod can set one, as long as it writes after the object is built and keeps writing. Each flag is read when the game needs it: `nohud`, for example, is read before a HUD element first shows, so it must be set from boot (Pinyon Shift's own HUD toggle uses a separate hidden byte instead, [UI, HUD and input](game-ui.md#hud-and-map)). This hides the HUD from the start:

```c
/* nohud: byte +3213 of the launch-options object at 0x832E29A0 (base game). */
static void on_frame(void* user, const PinyonHookEvent* event) {
  static const uint8_t on = 1;
  (void)user;
  (void)event;
  api->write_guest(0x832E29A0u + 3213, &on, 1);
}
```

Pinyon Shift sets three of these flags itself (the skippable voice-over, the idle intro replay and the automatic reset); the records below say which flags work, which are never read, and which were not tested. The game's online services are gone, and the records under [Online services](#online-services) show where it still checks for them, which matters for features such as the 1000 Club and the Treasure Map.

## Launch options

{{findings:systems/Launch options}}

## Debug and developer features

{{findings:systems/Debug and developer features}}

## Online services

{{findings:systems/Online services}}

## Leftover modes and hardware

{{findings:systems/Leftover modes and hardware}}

## Gameplay systems

{{findings:systems/Gameplay systems}}

## Data and tuning files

{{findings:systems/Data and tuning files}}

## Crash guards and helpers

{{findings:systems/Crash guards and helpers}}
