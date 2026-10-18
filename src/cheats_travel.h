#pragma once

#include <cstdint>
#include <optional>

#include "cheats_destination.h"

namespace pinyon_shift::cheats {

// UI snapshots contain coordinates only; guest objects stay on the guest thread.
std::optional<Destination> MapDestination();
// True means queued. The title may reject it; teleport waits for its map and
// expires after ten seconds. Neither return value certifies a landing.
bool RequestGpsDestination(const Destination& point);
bool RequestTeleportDestination(const Destination& point);
void UpdateDestinations();
void GpsDestinationApplied();
void TeleportDestinationApplied();

// Native map hooks. Neither replaces the title's travel or streaming sequence.
bool AllowMapTravel(uint32_t map, bool title_enabled);
bool PrepareMapTravelInput(uint32_t map);

}  // namespace pinyon_shift::cheats
