"""Custom radio stations for `pinyon.py radio` (#445).

FH1 has three music stations and the executable names them, their logos and
their option rows, so a custom station takes over one of the three slots:

  Radio1  HORIZON BASS ARENA   Hud/Radio/RS_BassArena.xds
  Radio2  HORIZON PULSE        Hud/Radio/RS_Pulse.xds
  Radio3  HORIZON ROCKS        Hud/Radio/RS_2Eleven.xds

A station has a name, the folders and files its music comes from, an
optional PNG logo, and whether its tracks replace the slot's playlist or are
added to it. The stations live in <state>/config/radio-stations.json; `build`
turns them into one asset mod, custom_radio (tools/build-fh1-radio.py writes
the bank and playlists), with the names in every language's MyProfile.str
and Tips.str and the logos re-encoded into the HUD textures, all as archive
members built from the player's own files:

  pinyon.py radio list
  pinyon.py radio create NAME [--slot Radio2] [--add]
  pinyon.py radio rename SLOT NAME
  pinyon.py radio delete SLOT
  pinyon.py radio add SLOT PATH...       (folders or audio files)
  pinyon.py radio remove SLOT PATH...
  pinyon.py radio logo SLOT PNG | --clear
  pinyon.py radio mode SLOT replace|add
  pinyon.py radio ffmpeg PATH | --clear
  pinyon.py radio build

Every command takes --state-root and --json. Encoding needs FFmpeg: the path
set with `radio ffmpeg`, PINYON_SHIFT_FFMPEG, or ffmpeg on the PATH. `build`
enables the mod, and with no stations left removes it and disables it.
"""
from __future__ import annotations

import argparse
import functools
import importlib.util
import json
import os
import shutil
import struct
import sys
import zipfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = Path("config") / "radio-stations.json"
SCHEMA = "pinyon-shift.radio-stations.v1"
MOD = "custom_radio"
NAME_LIMIT = 40
LOGO_ARCHIVE = "media/ui/textures/Horizon.zip"
STRINGS = "media/StringTables"
SLOTS = {
    "Radio1": {"stock": "HORIZON BASS ARENA", "logo": "Hud/Radio/RS_BassArena.xds",
               "profile": 0xA29E, "tip_title": 0x0B3A, "tip_text": 0xE484},
    "Radio2": {"stock": "HORIZON PULSE", "logo": "Hud/Radio/RS_Pulse.xds",
               "profile": 0xA31E, "tip_title": 0xF203, "tip_text": 0x0063},
    "Radio3": {"stock": "HORIZON ROCKS", "logo": "Hud/Radio/RS_2Eleven.xds",
               "profile": 0xA39E, "tip_title": 0x9730, "tip_text": 0x94AE},
}


class RadioError(RuntimeError):
    """A station change that cannot be made, with the reason for the player."""


@functools.lru_cache(maxsize=None)
def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(file))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def radio_builder():
    return _load("build_fh1_radio", "build-fh1-radio.py")


def ui_tools():
    return _load("inspect_fh1_ui", "inspect-fh1-ui.py")


def string_tools():
    return _load("fh1_strings", "fh1-strings.py")


# ---- the store ---------------------------------------------------------------


def load(state: Path) -> dict:
    path = state / STORE
    if not path.is_file():
        return {"schema": SCHEMA, "stations": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        raise RadioError(f"{path} is not a station list this version reads")
    return data


def save(state: Path, data: dict) -> None:
    path = state / STORE
    path.parent.mkdir(parents=True, exist_ok=True)
    data["stations"].sort(key=lambda s: s["slot"])
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes((json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    temporary.replace(path)


def slot_of(value: str) -> str:
    slot = f"Radio{value}" if value in ("1", "2", "3") else value[:1].upper() + value[1:].lower()
    if slot not in SLOTS:
        raise RadioError(f"{value} is not a station slot; use Radio1, Radio2 or Radio3")
    return slot


def find(data: dict, slot: str) -> dict:
    for station in data["stations"]:
        if station["slot"] == slot:
            return station
    raise RadioError(f"no custom station on {slot}")


def clean_name(name: str) -> str:
    name = " ".join(name.split())
    if not name:
        raise RadioError("a station needs a name")
    if len(name) > NAME_LIMIT:
        raise RadioError(f"station names are at most {NAME_LIMIT} characters")
    return name


def tracks(station: dict) -> tuple[list[Path], list[str]]:
    """The station's audio files in play order, and the sources now missing."""
    builder = radio_builder()
    files, missing = [], []
    for source in station["sources"]:
        path = Path(source)
        if path.is_dir():
            files += builder.find_music(path)
        elif path.is_file() and path.suffix.lower() in builder.AUDIO_SUFFIXES:
            files.append(path)
        else:
            missing.append(source)
    return list(dict.fromkeys(files)), missing


def describe(state: Path, data: dict) -> dict:
    stations = []
    for station in data["stations"]:
        files, missing = tracks(station)
        stations.append(dict(station, tracks=len(files), missing=missing,
                             replaces=SLOTS[station["slot"]]["stock"]))
    mod = state / "mods" / MOD
    built = mod / ".pinyon-radio"
    config = state / "config" / "pinyon_shift.toml"
    return {"stations": stations, "free_slots": [s for s in SLOTS
                                                  if s not in {x["slot"] for x in data["stations"]}],
            "ffmpeg": find_ffmpeg(data), "built": built.is_file(),
            "enabled": MOD in _patches().enabled_mods(config),
            "out_of_date": bool(data.get("changed")) or not built.is_file()}


def _patches():
    return _load("build_mod_patches", "build-mod-patches.py")


def find_ffmpeg(data: dict) -> str | None:
    for candidate in (data.get("ffmpeg"), os.environ.get("PINYON_SHIFT_FFMPEG")):
        if candidate and Path(candidate).is_file():
            return str(Path(candidate))
    return shutil.which("ffmpeg")


# ---- names and logos ---------------------------------------------------------


def string_members(game: Path, names: dict[str, str], extractor: Path) -> dict[str, bytes]:
    """Every language's MyProfile.str and Tips.str with the new names."""
    tools = string_tools()
    members = {}
    folder = game / STRINGS
    for archive in sorted(folder.glob("*.zip")) if folder.is_dir() else []:
        with zipfile.ZipFile(archive) as zipped:
            listed = {info.filename.lower(): info.filename for info in zipped.infolist()}
        for table in ("MyProfile.str", "Tips.str"):
            member = listed.get(table.lower())
            if member is None:
                continue
            data = tools.read_archive_entry(archive, member, extractor)
            present = dict(tools.parse(data))
            replacements = {}
            for slot, name in names.items():
                keys = SLOTS[slot]
                if table == "MyProfile.str":
                    replacements[keys["profile"]] = name.upper()
                else:
                    replacements[keys["tip_title"]] = name.upper()
                    replacements[keys["tip_text"]] = (
                        f"{name} plays music you chose in the Pinyon Shift launcher.")
            replacements = {k: v for k, v in replacements.items() if k in present}
            if replacements:
                path = f"{STRINGS}/{archive.name}/{member}"
                members[path] = tools.replace_strings(data, replacements)
    return members


def read_png(data: bytes) -> tuple[int, int, bytes]:
    """Decode an 8-bit, non-interlaced PNG of any color type to RGBA."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RadioError("the logo is not a PNG file")
    at, header, compressed, palette, transparency = 8, None, b"", b"", b""
    while at + 8 <= len(data):
        size, kind = struct.unpack_from(">I4s", data, at)
        body = data[at + 8:at + 8 + size]
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            palette = body
        elif kind == b"tRNS":
            transparency = body
        elif kind == b"IDAT":
            compressed += body
        at += 12 + size
    if header is None:
        raise RadioError("the logo PNG has no header")
    width, height, depth, color, _, _, interlace = header
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color)
    if depth != 8 or interlace or channels is None:
        raise RadioError("logos must be 8-bit, non-interlaced PNG files")
    raw, stride = zlib.decompress(compressed), channels * width
    rows, previous = [], bytearray(stride)
    for row in range(height):
        line = raw[row * (stride + 1):(row + 1) * (stride + 1)]
        kind, current = line[0], bytearray(line[1:])
        for i in range(stride):
            left = current[i - channels] if i >= channels else 0
            up, corner = previous[i], previous[i - channels] if i >= channels else 0
            if kind == 1:
                current[i] = (current[i] + left) & 0xFF
            elif kind == 2:
                current[i] = (current[i] + up) & 0xFF
            elif kind == 3:
                current[i] = (current[i] + (left + up) // 2) & 0xFF
            elif kind == 4:
                estimate = left + up - corner
                distances = (abs(estimate - left), abs(estimate - up), abs(estimate - corner))
                current[i] = (current[i] + (left, up, corner)[distances.index(min(distances))]) & 0xFF
        rows.append(current)
        previous = current
    rgba = bytearray(4 * width * height)
    for y, row in enumerate(rows):
        for x in range(width):
            at = 4 * (y * width + x)
            if color == 6:
                rgba[at:at + 4] = row[4 * x:4 * x + 4]
            elif color == 2:
                rgba[at:at + 4] = bytes(row[3 * x:3 * x + 3]) + b"\xff"
            elif color == 4:
                rgba[at:at + 4] = bytes((row[2 * x],) * 3 + (row[2 * x + 1],))
            elif color == 0:
                rgba[at:at + 4] = bytes((row[x],) * 3) + b"\xff"
            else:
                index = row[x]
                alpha = transparency[index] if index < len(transparency) else 255
                rgba[at:at + 4] = palette[3 * index:3 * index + 3] + bytes((alpha,))
    return width, height, bytes(rgba)


def fit(width: int, height: int, rgba: bytes, out_width: int, out_height: int) -> bytes:
    """Scale to fit inside the target, centred on transparency, averaging
    the source pixels each target pixel covers (premultiplied by alpha)."""
    scale = min(out_width / width, out_height / height)
    fitted_w, fitted_h = max(1, round(width * scale)), max(1, round(height * scale))
    left, top = (out_width - fitted_w) // 2, (out_height - fitted_h) // 2
    sums = [[0.0] * 5 for _ in range(out_width * out_height)]
    for y in range(height):
        ty = top + min(fitted_h - 1, int(y * fitted_h / height))
        for x in range(width):
            tx = left + min(fitted_w - 1, int(x * fitted_w / width))
            at = 4 * (y * width + x)
            r, g, b, a = rgba[at:at + 4]
            cell = sums[ty * out_width + tx]
            cell[0] += r * a
            cell[1] += g * a
            cell[2] += b * a
            cell[3] += a
            cell[4] += 1
    out = bytearray(4 * out_width * out_height)
    for index, (r, g, b, a, count) in enumerate(sums):
        if count and a:
            out[4 * index:4 * index + 4] = bytes((round(r / a), round(g / a), round(b / a),
                                                  round(a / count)))
    return bytes(out)


def _to565(color) -> int:
    r, g, b = (max(0, min(255, round(c))) for c in color)
    return ((r * 31 + 127) // 255) << 11 | ((g * 63 + 127) // 255) << 5 | (b * 31 + 127) // 255


def encode_bc3_block(texels: list[tuple[int, int, int, int]]) -> bytes:
    """One DXT5 block: endpoints along the colors' main axis, nearest indices."""
    ui = ui_tools()
    alphas = [t[3] for t in texels]
    a0, a1 = max(alphas), min(alphas)
    if a0 == a1:
        alpha_block = bytes((a0, a1)) + bytes(6)
    else:
        palette = [a0, a1] + [((7 - i) * a0 + i * a1 + 3) // 7 for i in range(1, 7)]
        bits = 0
        for index, value in enumerate(alphas):
            best = min(range(8), key=lambda k: abs(palette[k] - value))
            bits |= best << (3 * index)
        alpha_block = bytes((a0, a1)) + bits.to_bytes(6, "little")
    visible = [t[:3] for t in texels if t[3]] or [t[:3] for t in texels]
    mean = [sum(c[i] for c in visible) / len(visible) for i in range(3)]
    axis = [1.0, 1.0, 1.0]
    for _ in range(4):
        moved = [sum((c[i] - mean[i]) * sum((c[j] - mean[j]) * axis[j] for j in range(3))
                     for c in visible) for i in range(3)]
        length = max(abs(v) for v in moved)
        if not length:
            break
        axis = [v / length for v in moved]
    projections = [sum((c[i] - mean[i]) * axis[i] for i in range(3)) for c in visible]
    high = visible[projections.index(max(projections))]
    low = visible[projections.index(min(projections))]
    color0, color1 = _to565(high), _to565(low)
    head = struct.pack("<HH", color0, color1)
    palette = ui._bc1_colors(head + bytes(4), False)
    indices = 0
    for index, texel in enumerate(texels):
        best = min(range(4), key=lambda k: sum((palette[k][i] - texel[i]) ** 2 for i in range(3)))
        indices |= best << (2 * index)
    return alpha_block + head + struct.pack("<I", indices)


def encode_logo(stock: bytes, png: bytes) -> bytes:
    """The stock DXT5 logo texture with the PNG fitted into it."""
    ui = ui_tools()
    header = ui.parse_xds(stock)
    if header["format_number"] not in (20, 53):
        raise RadioError(f"the stock logo is {header['format']}, not DXT5")
    width, height = header["width"], header["height"]
    rgba = fit(*read_png(png), width, height)
    mask = ui.ENDIAN_MASKS[header["endianness"]]
    output = bytearray(stock)
    for x, y, offset in ui._base_level_blocks(header):
        texels = []
        for index in range(16):
            tx, ty = min(width - 1, 4 * x + index % 4), min(height - 1, 4 * y + index // 4)
            at = 4 * (ty * width + tx)
            texels.append(tuple(rgba[at:at + 4]))
        block = encode_bc3_block(texels)
        at = ui.XDS_HEADER_SIZE + offset
        for index in range(16):
            output[at + (index ^ mask)] = block[index]
    return bytes(output)


def logo_members(game: Path, logos: dict[str, Path], extractor: Path) -> dict[str, bytes]:
    if not logos:
        return {}
    ui = ui_tools()
    archive = game / LOGO_ARCHIVE
    with zipfile.ZipFile(archive) as zipped:
        listed = {info.filename.lower(): info for info in zipped.infolist()}
    members = {}
    for slot, png in logos.items():
        info = listed.get(SLOTS[slot]["logo"].lower())
        if info is None:
            raise RadioError(f"{SLOTS[slot]['logo']} is not in {archive}")
        stock = ui.extract_entry(archive, info, extractor, "auto", 1 << 24)
        members[f"{LOGO_ARCHIVE}/{info.filename}"] = encode_logo(stock, Path(png).read_bytes())
    return members


# ---- commands ----------------------------------------------------------------


def find_extractor(build: str | None) -> Path:
    import pinyon_assets
    extractor = pinyon_assets.find_tool("pinyon_shift_fh1_archive_extract",
                                 Path(build).resolve() if build else None)
    if extractor is None:
        raise RadioError("the archive extractor is missing; build pinyon_shift_fh1_archive_extract")
    return extractor


def build(state: Path, game: Path, data: dict, build_directory: str | None, log) -> dict:
    patches = _patches()
    config = state / "config" / "pinyon_shift.toml"
    mod = state / "mods" / MOD
    builder = radio_builder()
    if not data["stations"]:
        if mod.exists():
            if not (mod / builder.MARKER).exists():
                raise RadioError(f"{mod} was not made by Pinyon Shift; leaving it alone")
            shutil.rmtree(mod)
        patches.set_enabled_mods(config, [m for m in patches.enabled_mods(config) if m != MOD])
        data.pop("changed", None)
        save(state, data)
        return {"result": "removed", "mod": str(mod)}
    stations, names, logos = [], {}, {}
    for station in data["stations"]:
        files, missing = tracks(station)
        if missing:
            raise RadioError(f"{station['name']}: {', '.join(missing)} cannot be found")
        if not files:
            raise RadioError(f"{station['name']} has no music yet; add a folder or files")
        stations.append(builder.Station(station["slot"], files, station["mode"] == "replace"))
        names[station["slot"]] = station["name"]
        if station.get("logo"):
            if not Path(station["logo"]).is_file():
                raise RadioError(f"{station['name']}: the logo {station['logo']} cannot be found")
            logos[station["slot"]] = Path(station["logo"])
    extractor = find_extractor(build_directory)
    members = string_members(game, names, extractor)
    members.update(logo_members(game, logos, extractor))
    ffmpeg = find_ffmpeg(data)
    if not ffmpeg:
        raise RadioError("FFmpeg is needed to encode the music; set its path with "
                         "`radio ffmpeg` or put ffmpeg on the PATH")
    ffprobe = Path(ffmpeg).with_name(Path(ffmpeg).name.replace("ffmpeg", "ffprobe"))
    try:
        result = builder.build_stations(state, MOD, stations, game, ffmpeg,
                                        str(ffprobe) if ffprobe.is_file() else shutil.which("ffprobe"),
                                        log=log, members=members)
    except (builder.BuildError, RuntimeError, ValueError) as error:
        raise RadioError(str(error)) from error
    mods = patches.enabled_mods(config)
    if MOD not in mods:
        patches.set_enabled_mods(config, mods + [MOD])
    data.pop("changed", None)
    save(state, data)
    return {"result": "built", "mod": result["mod"], "tracks": result["tracks"],
            "playlists": result["stations"], "members": sorted(members)}


def run(args: argparse.Namespace) -> dict:
    state = Path(args.state_root or ROOT / ".local" / "preview").resolve()
    game = Path(args.game_root or ROOT / ".local" / "game" / "base").resolve()
    data = load(state)
    command = args.radio_command
    if command == "list":
        return describe(state, data)
    if command == "build":
        log = (lambda line: None) if args.json else print
        return build(state, game, data, args.build_directory, log)
    if command == "ffmpeg":
        if args.clear:
            data.pop("ffmpeg", None)
        else:
            if not args.path or not Path(args.path).is_file():
                raise RadioError("give the path of ffmpeg itself, or --clear")
            data["ffmpeg"] = str(Path(args.path).resolve())
        save(state, data)
        return describe(state, data)
    if command == "create":
        taken = {s["slot"] for s in data["stations"]}
        slot = slot_of(args.slot) if args.slot else next((s for s in SLOTS if s not in taken), None)
        if slot is None:
            raise RadioError("all three station slots have a custom station; delete one first")
        if slot in taken:
            raise RadioError(f"{slot} already has a custom station")
        data["stations"].append({"slot": slot, "name": clean_name(args.name),
                                 "mode": "add" if args.add else "replace", "sources": [],
                                 "logo": None})
    else:
        station = find(data, slot_of(args.slot))
        if command == "rename":
            station["name"] = clean_name(args.name)
        elif command == "delete":
            data["stations"].remove(station)
        elif command == "mode":
            station["mode"] = args.mode
        elif command == "add":
            for path in args.paths:
                resolved = Path(path).resolve()
                if not resolved.exists():
                    raise RadioError(f"{path} does not exist")
                if str(resolved) not in station["sources"]:
                    station["sources"].append(str(resolved))
        elif command == "remove":
            wanted = {str(Path(path).resolve()).lower() for path in args.paths}
            station["sources"] = [s for s in station["sources"] if s.lower() not in wanted]
        elif command == "logo":
            if args.clear:
                station["logo"] = None
            else:
                if not args.png:
                    raise RadioError("give a PNG file, or --clear")
                read_png(Path(args.png).read_bytes())
                station["logo"] = str(Path(args.png).resolve())
    data["changed"] = True
    save(state, data)
    return describe(state, data)


def add_parser(commands) -> None:
    parser = commands.add_parser("radio", help="custom radio stations from your own music")
    sub = parser.add_subparsers(dest="radio_command", required=True)

    def command(name: str, help_text: str):
        child = sub.add_parser(name, help=help_text)
        child.add_argument("--state-root")
        child.add_argument("--game-root")
        child.add_argument("--json", action="store_true")
        return child

    command("list", "show the custom stations")
    create = command("create", "make a station on a free slot")
    create.add_argument("name")
    create.add_argument("--slot", help="Radio1, Radio2 or Radio3 (default: the first free)")
    create.add_argument("--add", action="store_true",
                        help="add the music to the stock playlist instead of replacing it")
    rename = command("rename", "rename a station")
    rename.add_argument("slot")
    rename.add_argument("name")
    command("delete", "delete a station; its slot plays the stock station again").add_argument("slot")
    for name, help_text in (("add", "add folders or audio files"),
                            ("remove", "remove folders or files")):
        child = command(name, help_text)
        child.add_argument("slot")
        child.add_argument("paths", nargs="+")
    logo = command("logo", "set the station's logo from a PNG")
    logo.add_argument("slot")
    logo.add_argument("png", nargs="?")
    logo.add_argument("--clear", action="store_true")
    mode = command("mode", "replace the stock playlist, or add to it")
    mode.add_argument("slot")
    mode.add_argument("mode", choices=("replace", "add"))
    ffmpeg = command("ffmpeg", "set the FFmpeg used to encode the music")
    ffmpeg.add_argument("path", nargs="?")
    ffmpeg.add_argument("--clear", action="store_true")
    command("build", "build and enable the custom_radio mod").add_argument("--build-directory")


def main(args: argparse.Namespace) -> int:
    try:
        result = run(args)
    except (RadioError, OSError, json.JSONDecodeError) as error:
        if args.json:
            print(json.dumps({"result": "error", "error": str(error)}))
        else:
            print(f"error: {error}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        for station in result.get("stations", []):
            print(f"{station['slot']}: {station['name']} ({station['mode']}, "
                  f"{station['tracks']} tracks, instead of {station['replaces']})")
        for key, value in result.items():
            if key != "stations":
                print(f"{key}: {value}")
    return 0
