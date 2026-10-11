#pragma once

#include <filesystem>
#include <functional>
#include <string>

namespace pinyon_shift::music {

// Your music (#420, FB-1.2): the player's own MP3 and WAV files play on the
// host instead of the game's radio. Turning it on tells the title the
// system's music player has the music, as a 360 dashboard soundtrack did,
// so the title mutes its own radio by its own path.
//
// Applies the pinyon_shift_music* settings now and whenever they change;
// `post_to_ui` runs a task on the UI thread.
void Install(std::function<void(std::function<void()>)> post_to_ui);
// Whether the title has a world (free roam, events, the festival's menus).
// The music plays only then, so the title screen keeps the game's own music
// (#445); called from the title's frame.
void SetInGame(bool in_game);
// Stops the music and drops the callbacks, before the kernel goes away.
void Shutdown();

// The folder music is read from: pinyon_shift_music_folder, or
// <state>/music.
std::filesystem::path Folder();

// The line under the AUDIO page: what is playing, or how to add music.
std::string StatusLine();

void Next();
void Previous();

}  // namespace pinyon_shift::music
