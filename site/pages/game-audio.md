---
title: Audio and radio
section: Reverse engineering
order: 12
description: Forza Horizon's FMOD Ex audio: the audio manager and its cues, the XMA output, speech and ambience banks, the radio's single MP3 music bank, its station list and playlists, and why the selectable stations are fixed in code.
---

# Audio and radio

All of the game's sound goes through **FMOD Ex**: event projects (`.fev`) name cues, and 984 sound banks (`.fsb`) under `media/audio` hold the samples. One audio manager object owns the FMOD system, and simulation code reaches it through `CAudioManagerDeferred` commands ([The executable](game-executable.md#classes)). The audio thread writes the mixed output as 48 kHz six-channel XMA through the console's XMA hardware.

The radio is simpler than it looks. All its music is one 680 MB bank of plain MP3 samples, `Radio_Music.fsb`, and an XML file lists the stations and which samples each may play. That is why custom stations are possible as data mods ([Modding](modding.md#custom-radio-stations)), while adding a fourth selectable station is not: the station names and their icons are in the executable.

An FSB4 bank's header lists its samples, and each radio sample carries three named sync points. This reads them without decoding any audio:

```python
import struct


def fsb4_samples(path):
    """(name, length in samples, frequency, sync points) for each sample of an FSB4 bank."""
    with open(path, "rb") as bank:
        magic, count, header_size = struct.unpack("<4sII", bank.read(48)[:12])
        assert magic == b"FSB4"
        headers = bank.read(header_size)  # sample headers; the audio data follows
    offset = 0
    for _ in range(count):
        size = struct.unpack_from("<H", headers, offset)[0]
        name = headers[offset + 2:offset + 32].split(b"\0")[0].decode("ascii")
        length, _, _, _, _, frequency = struct.unpack_from("<IIIIIi", headers, offset + 32)
        sync = []
        if headers[offset + 80:offset + 84] == b"SYNC":   # named markers, 260 bytes each
            for k in range(struct.unpack_from("<I", headers, offset + 84)[0]):
                entry = offset + 88 + 260 * k
                label = headers[entry + 4:entry + 260].split(b"\0")[0].decode("ascii")
                sync.append((label, struct.unpack_from("<I", headers, entry)[0]))
        yield name, length, frequency, sync
        offset += size
```

On `Radio_Music.fsb` it yields 127 samples, each with `SongStart`, `EventStart` and `IdentStart` markers. Unlike the game's archives, FSB4 headers are little-endian. `tools/build-fh1-radio.py --check-bank` parses the whole bank and rebuilds its header byte for byte.

## Audio engine

The title's output is XMA, written by the audio thread through the console's XMA registers. In the recompiled game those writes never fault: the generator recognises the register window when the address is built and emits each store as a direct call into the runtime's decoder, so the hardware path is nine small XAUDIO2 routines calling the decoder about 115 times a frame. The decoder's register handler used to decode each kicked context on the audio thread itself; the SDK cvar `xma_decode_kicks_inline=false` leaves that to the decoder thread, which measured 15 % fewer audio-thread cycles on the desktop and 21 % fewer instructions on the Odin with no stall or queue change ([research record](https://github.com/arcanite24/pinyon-shift/blob/dev/docs/NEXT_LEVEL_RESEARCH.md), NL-4.1). It stays off by default until a race has been listened to with it on.

{{findings:audio/Audio engine}}

## Speech and ambience banks

{{findings:audio/Speech and ambience banks}}

## Radio banks and playlists

{{findings:audio/Radio banks and playlists}}

## Radio presentation

{{findings:audio/Radio presentation}}
