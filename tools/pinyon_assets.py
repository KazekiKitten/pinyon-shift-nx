"""Export the player's own game assets to standard formats (#446).

  pinyon.py assets inventory [--include-dlc] [--include-v4] [--json]
  pinyon.py assets export --out <dir> [--kind audio,textures,models,video,strings,db]
                          [--filter <glob>] [--include-dlc] [--include-v4]
                          [--audio-format wav|flac|ogg] [--jobs N] [--json]

Only the player's own verified files are read: the extracted game checked
against config/supported-extracted-ms-2505.json (path and size), the DLC
packages the launcher imported and the v4 title update it installed. Nothing
is written outside the chosen folder, nothing is uploaded or cached, and the
exports stay the property of Microsoft and Playground Games: they are for the
player's personal use only and must not be redistributed (docs/LEGAL.md).

| Kind | Source | Output |
| --- | --- | --- |
| audio | FSB4 banks (`.fsb`) | WAV per sample (FLAC/OGG with FFmpeg) |
| textures | `.xds` (and `.dds`, `.tga`, `.xpr` as stored) | DDS and PNG, untiled and byte-swapped |
| models | `.carbin`, `.rmb.bin`, `.pgeo`, `.gr2`, `.skinbin` | copied as stored (not yet decoded) |
| video | `.wmv` | copied as stored |
| strings | LSB2 string tables (`.str`) | JSON and CSV |
| db | `gamedb.slt` (SQLite), `.xml`, `.ini`, `.lst`, `.sch` | copied, SQLite also as CSV and JSON |

`--filter` matches an asset's path inside its source, case-insensitively,
such as `media/cars/*` or `*.str`; archive members are matched as
`<archive>/<member>`. `assets.json` in the output folder lists every asset,
what it became and any error. Archive members (XMem LZX) are read with the
build's `pinyon_shift_fh1_archive_extract`, banks are decoded with
`pinyon_shift_fh1_audio_decode`.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import fnmatch
import functools
import importlib.util
import io
import json
import os
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "config/supported-extracted-ms-2505.json"
TITLE_UPDATES = ROOT / "config/supported-title-updates.json"
KINDS = ("audio", "textures", "models", "video", "strings", "db")
# By file name ending, longest first.
EXTENSIONS = (
    (".rmb.bin", "models"), (".carbin", "models"), (".pgeo", "models"), (".gr2", "models"),
    (".skinbin", "models"),
    (".fsb", "audio"),
    (".xds", "textures"), (".dds", "textures"), (".tga", "textures"), (".xpr", "textures"),
    (".wmv", "video"),
    (".str", "strings"),
    (".slt", "db"), (".xml", "db"), (".ini", "db"), (".lst", "db"), (".sch", "db"),
)
NOTICE = (
    "These files were exported from your own copy of Forza Horizon by Pinyon Shift.\n"
    "They remain the property of Microsoft and Playground Games. They are for your\n"
    "personal use only (for example to listen to, view or study them); do not\n"
    "redistribute, upload or share them. Pinyon Shift never uploads, shares or\n"
    "caches them.\n"
)
SCHEMA = "pinyon-shift.asset-export.v1"
INDEX = "assets.json"
AUDIO_FORMATS = ("wav", "flac", "ogg")


class AssetError(RuntimeError):
    """An export that cannot run, with the reason for the player."""


@functools.lru_cache(maxsize=None)
def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(file))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def kind_of(name: str) -> str | None:
    lower = name.lower()
    for ending, kind in EXTENSIONS:
        if lower.endswith(ending):
            return kind
    return None


# ---- sources -----------------------------------------------------------------


@dataclass
class Source:
    """A verified root of game files: the base game, a DLC package, the update."""
    label: str  # base, dlc/<package id>, v4
    root: Path
    files: list[str] = field(default_factory=list)  # posix paths under root


def base_source(game: Path) -> Source:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    if not (game / "default.xex").is_file():
        raise AssetError(f"no game files at {game}; run the setup first")
    source = Source("base", game)
    for entry in catalog["files"]:
        path = game / entry["guest_path"]
        # The setup checked every file's hash; a size change means it was edited since.
        if path.is_file() and path.stat().st_size == entry["size_bytes"]:
            source.files.append(entry["guest_path"])
    if not source.files:
        raise AssetError(f"the game files at {game} do not match the supported dump")
    return source


def dlc_sources(state: Path) -> list[Source]:
    dlc = _load("manage_fh1_dlc", "manage-fh1-dlc.py")
    sources = []
    for record in dlc.list_content(state):
        if record.get("status") != "gameplay_unverified":
            continue  # Only intact packages the launcher imported and checked.
        enabled, disabled, _ = dlc.package_paths(state, record["package_id"])
        root = enabled if enabled.is_dir() else disabled
        source = Source(f"dlc/{record['package_id']}", root)
        source.files = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
        sources.append(source)
    return sources


def v4_source(state: Path) -> Source | None:
    folder = state / "title-update-v4"
    manifest = json.loads(TITLE_UPDATES.read_text(encoding="utf-8"))
    source = Source("v4", folder)
    for entry in manifest["updates"][0]["files"]:
        path = folder / entry["guest_path"]
        if path.is_file() and path.stat().st_size == entry["size_bytes"]:
            source.files.append(entry["guest_path"])
    return source if source.files else None


def gather_sources(args: argparse.Namespace) -> list[Source]:
    state = Path(args.state_root or ROOT / ".local/preview").resolve()
    game = Path(args.game_root or ROOT / ".local/game/base").resolve()
    sources = [base_source(game)]
    if args.include_dlc:
        sources += dlc_sources(state)
    if args.include_v4:
        update = v4_source(state)
        if update is None:
            raise AssetError("the v4 title update is not installed; add it in the launcher first")
        sources.append(update)
    return sources


# ---- the plan ----------------------------------------------------------------


@dataclass
class Item:
    source: str           # Source label
    path: str             # path inside the source, archive members as <zip>/<member>
    kind: str
    archive: str | None = None  # the archive's path inside the source
    member: str | None = None


def wanted(path: str, kinds: set[str], pattern: str | None) -> str | None:
    kind = kind_of(path)
    if kind is None or kind not in kinds:
        return None
    if pattern and not fnmatch.fnmatch(path.lower(), pattern.lower()):
        return None
    return kind


def plan(sources: list[Source], kinds: set[str], pattern: str | None) -> list[Item]:
    items = []
    for source in sources:
        for path in source.files:
            if path.lower().endswith(".zip"):
                try:
                    with zipfile.ZipFile(source.root / path) as archive:
                        names = [i.filename for i in archive.infolist() if not i.is_dir()]
                except (OSError, zipfile.BadZipFile):
                    continue
                for name in names:
                    member = f"{path}/{name.replace(chr(92), '/')}"
                    kind = wanted(member, kinds, pattern)
                    if kind:
                        items.append(Item(source.label, member, kind, path, name))
                continue
            kind = wanted(path, kinds, pattern)
            if kind:
                items.append(Item(source.label, path, kind))
    return items


# ---- exporters ---------------------------------------------------------------
# Each takes the file's bytes on disk and the output stem (the asset's path in
# the output folder without its extension) and returns the files it wrote,
# relative to the output folder.


def _rel(out: Path, path: Path) -> str:
    return path.relative_to(out).as_posix()


def export_copy(data: Path, stem: Path, out: Path, suffix: str) -> list[str]:
    target = stem.with_name(stem.name + suffix)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(data, target)
    return [_rel(out, target)]


DDS_FOURCC = {18: b"DXT1", 51: b"DXT1", 19: b"DXT3", 52: b"DXT3", 20: b"DXT5", 53: b"DXT5",
              59: b"ATI1"}


def dds_bytes(width: int, height: int, fourcc: bytes | None, payload: bytes) -> bytes:
    """A DDS file with one level: block-compressed by `fourcc`, else RGBA8."""
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | (0x80000 if fourcc else 0x8)
    if fourcc:
        block = 8 if fourcc in (b"DXT1", b"ATI1") else 16
        pitch = max(1, (width + 3) // 4) * max(1, (height + 3) // 4) * block
        pixel_format = struct.pack("<II4sIIIII", 32, 0x4, fourcc, 0, 0, 0, 0, 0)
    else:
        pitch = width * 4
        pixel_format = struct.pack("<II4sIIIII", 32, 0x41, b"\0\0\0\0", 32,
                                   0x000000FF, 0x0000FF00, 0x00FF0000, 0xFF000000)
    header = struct.pack("<4sIIIIIII", b"DDS ", 124, flags, height, width, pitch, 0, 1)
    header += b"\0" * 44 + pixel_format + struct.pack("<IIIII", 0x1000, 0, 0, 0, 0)
    return header + payload


def export_xds(data: Path, stem: Path, out: Path) -> list[str]:
    ui = _load("inspect_fh1_ui", "inspect-fh1-ui.py")
    raw = data.read_bytes()
    header, rgba = ui.decode_xds(raw)
    width, height = header["width"], header["height"]
    number = header["format_number"]
    fourcc = DDS_FOURCC.get(number)
    if fourcc:
        # The base level's blocks, untiled and in the PC's byte order.
        _, block, block_bytes = ui.TEXTURE_FORMATS[number]
        columns = (width + block - 1) // block
        rows = (height + block - 1) // block
        blocks = bytearray(columns * rows * block_bytes)
        payload = raw[ui.XDS_HEADER_SIZE:]
        for x, y, offset in ui._base_level_blocks(header):
            at = (y * columns + x) * block_bytes
            blocks[at:at + block_bytes] = ui._unswap(payload, offset, block_bytes,
                                                     header["endianness"])
        dds = dds_bytes(width, height, fourcc, bytes(blocks))
    else:
        dds = dds_bytes(width, height, None, rgba)
    stem.parent.mkdir(parents=True, exist_ok=True)
    dds_path = stem.with_name(stem.name + ".dds")
    png_path = stem.with_name(stem.name + ".png")
    dds_path.write_bytes(dds)
    png_path.write_bytes(ui.encode_png(width, height, rgba))
    return [_rel(out, dds_path), _rel(out, png_path)]


def export_strings(data: Path, stem: Path, out: Path) -> list[str]:
    strings = _load("fh1_strings", "fh1-strings.py")
    entries = strings.parse(data.read_bytes())
    stem.parent.mkdir(parents=True, exist_ok=True)
    json_path = stem.with_name(stem.name + ".json")
    csv_path = stem.with_name(stem.name + ".csv")
    json_path.write_text(json.dumps([{"key": f"0x{key:04X}", "text": text} for key, text in entries],
                                    ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["key", "text"])
        for key, text in entries:
            writer.writerow([f"0x{key:04X}", text])
    return [_rel(out, json_path), _rel(out, csv_path)]


def _cell(value):
    return value.hex() if isinstance(value, bytes) else value


def export_sqlite(data: Path, stem: Path, out: Path, suffix: str) -> list[str]:
    written = export_copy(data, stem, out, suffix)
    tables_dir = stem.with_name(stem.name + ".tables")
    tables_dir.mkdir(parents=True, exist_ok=True)
    dump = {}
    # Read the copy, never the game's own file, and only for reading.
    uri = (out / written[0]).resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        names = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        for name in names:
            cursor = connection.execute(f'SELECT * FROM "{name.replace(chr(34), chr(34) * 2)}"')
            columns = [column[0] for column in cursor.description]
            rows = [[_cell(value) for value in row] for row in cursor]
            safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
            table_path = tables_dir / f"{safe}.csv"
            with table_path.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(columns)
                writer.writerows(rows)
            written.append(_rel(out, table_path))
            dump[name] = [dict(zip(columns, row)) for row in rows]
    json_path = stem.with_name(stem.name + ".json")
    json_path.write_text(json.dumps(dump, ensure_ascii=False) + "\n", encoding="utf-8")
    written.append(_rel(out, json_path))
    return written


def export_fsb(data: Path, stem: Path, out: Path, decoder: Path, audio_format: str,
               ffmpeg: str | None) -> list[str]:
    folder = stem.with_name(stem.name + ".fsb")
    folder.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run([str(decoder), str(data), str(folder)], capture_output=True,
                               text=True, encoding="utf-8", errors="replace")
    written, failed = [], 0
    for line in completed.stdout.splitlines():
        try:
            sample = json.loads(line)
        except ValueError:
            continue
        if "file" not in sample:
            failed += 1
            continue
        wav = folder / sample["file"]
        if audio_format != "wav":
            target = wav.with_suffix("." + audio_format)
            codec = ["-c:a", "flac"] if audio_format == "flac" else ["-c:a", "libvorbis", "-q:a", "6"]
            result = subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(wav), *codec, str(target)],
                                    capture_output=True, text=True)
            if result.returncode != 0:
                failed += 1
                continue
            wav.unlink()
            wav = target
        written.append(_rel(out, wav))
    if completed.returncode not in (0, 3) or not written:
        raise AssetError(completed.stderr.strip() or "no samples decoded")
    if failed:
        raise PartialExport(written, f"{failed} samples not decoded")
    return written


class PartialExport(Exception):
    def __init__(self, written: list[str], message: str):
        super().__init__(message)
        self.written = written


@dataclass
class Settings:
    out: Path
    decoder: Path | None
    audio_format: str
    ffmpeg: str | None


def export_one(item: Item, data: Path, settings: Settings) -> dict:
    """Exports one asset; the index entry for it."""
    out = settings.out
    relative = PurePosixPath(item.source) / item.path
    lower = item.path.lower()
    ending = next(e for e, _ in EXTENSIONS if lower.endswith(e))
    stem = out / item.kind / relative.parent / relative.name[:len(relative.name) - len(ending)]
    entry = {"source": item.source, "path": item.path, "kind": item.kind,
             "bytes": data.stat().st_size}
    try:
        if item.kind == "audio":
            entry["outputs"] = export_fsb(data, stem, out, settings.decoder, settings.audio_format,
                                          settings.ffmpeg)
        elif ending == ".xds":
            try:
                entry["outputs"] = export_xds(data, stem, out)
            except ValueError as error:  # Cube maps, volumes and unknown formats.
                entry["outputs"] = export_copy(data, stem, out, ending)
                entry["note"] = f"copied as stored: {error}"
        elif item.kind == "strings":
            entry["outputs"] = export_strings(data, stem, out)
        elif ending == ".slt":
            entry["outputs"] = export_sqlite(data, stem, out, ending)
        else:
            entry["outputs"] = export_copy(data, stem, out, ending)
            if item.kind == "models":
                entry["note"] = "copied as stored; the model formats are not decoded yet"
    except PartialExport as error:
        entry["outputs"] = error.written
        entry["error"] = str(error)
    except (AssetError, OSError, ValueError, sqlite3.Error, struct.error) as error:
        entry["error"] = str(error) or type(error).__name__
    return entry


# ---- running -----------------------------------------------------------------


def find_tool(name: str, build: Path | None) -> Path | None:
    executable = name + (".exe" if os.name == "nt" else "")
    candidates = [build] if build else []
    platform = {"win32": "win", "darwin": "macos"}.get(sys.platform, "linux")
    candidates += [ROOT / "out/build" / f"{platform}-{arch}-{config}"
                   for config in ("release", "relwithdebinfo")
                   for arch in ("amd64", "arm64")]
    for folder in candidates:
        if folder and (folder / executable).is_file():
            return folder / executable
    return None


class Progress:
    def __init__(self, json_mode: bool):
        self.json_mode = json_mode

    def __call__(self, percent: float, message: str) -> None:
        if self.json_mode:
            print("::pinyon::" + json.dumps({"stage": "export", "percent": round(percent, 1),
                                             "message": message}), flush=True)


def prepare_output(out: Path) -> None:
    if out.exists() and not out.is_dir():
        raise AssetError(f"{out} is not a folder")
    if out.is_dir() and any(out.iterdir()) and not (out / INDEX).is_file():
        raise AssetError(f"{out} is not empty; choose an empty folder or an earlier export")
    out.mkdir(parents=True, exist_ok=True)


def extract_archive(archive: Path, members: list[str], work: Path, extractor: Path | None) -> None:
    """Every wanted member under `work`: stored and deflated ones with Python,
    XMem LZX ones with the native extractor in one run."""
    native = False
    with zipfile.ZipFile(archive) as reader:
        infos = {info.filename: info for info in reader.infolist()}
        for name in members:
            info = infos[name]
            if info.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                target = work / name.replace(chr(92), "/")
                if not target.resolve().is_relative_to(work.resolve()):
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    target.write_bytes(reader.read(info))
                except (zipfile.BadZipFile, OSError, ValueError, NotImplementedError):
                    target.unlink(missing_ok=True)
            else:
                native = True
    if native:
        if extractor is None:
            raise AssetError("the archive extractor is missing; build the game first")
        subprocess.run([str(extractor), "--archive-all", str(archive), str(work)],
                       capture_output=True, check=False)


def export(args: argparse.Namespace) -> dict:
    kinds = set(args.kind.split(",")) if args.kind else set(KINDS)
    unknown = kinds - set(KINDS)
    if unknown:
        raise AssetError(f"unknown kind {', '.join(sorted(unknown))}; choose from {', '.join(KINDS)}")
    if args.audio_format not in AUDIO_FORMATS:
        raise AssetError(f"--audio-format is one of {', '.join(AUDIO_FORMATS)}")
    progress = Progress(args.json)
    out = Path(args.out).resolve()
    sources = gather_sources(args)
    items = plan(sources, kinds, args.filter)
    if not items:
        raise AssetError("nothing matches; check --kind and --filter")
    build = Path(args.build_directory).resolve() if args.build_directory else None
    extractor = find_tool("pinyon_shift_fh1_archive_extract", build)
    decoder = find_tool("pinyon_shift_fh1_audio_decode", build)
    ffmpeg = args.ffmpeg or shutil.which("ffmpeg")
    if "audio" in kinds and any(i.kind == "audio" for i in items):
        if decoder is None:
            raise AssetError("the audio decoder is missing; build pinyon_shift_fh1_audio_decode")
        if args.audio_format != "wav" and not ffmpeg:
            raise AssetError(f"{args.audio_format.upper()} needs FFmpeg on the PATH (or --ffmpeg); "
                             "WAV does not")
    prepare_output(out)
    (out / "NOTICE.txt").write_text(NOTICE, encoding="utf-8")
    settings = Settings(out, decoder, args.audio_format, ffmpeg)
    roots = {source.label: source.root for source in sources}
    # Loose files, then each archive's members together.
    groups: dict[tuple[str, str | None], list[Item]] = {}
    for item in items:
        groups.setdefault((item.source, item.archive), []).append(item)
    entries: list[dict] = []
    done = 0
    jobs = max(1, args.jobs or os.cpu_count() or 1)
    work_root = Path(tempfile.mkdtemp(prefix=".work-", dir=out))
    try:
        # The texture decoder is pure Python: processes, not threads.
        with concurrent.futures.ProcessPoolExecutor(jobs) as pool:
            for (label, archive), group in groups.items():
                root = roots[label]
                if archive is None:
                    tasks = [(item, root / item.path) for item in group]
                    work = None
                else:
                    work = Path(tempfile.mkdtemp(dir=work_root))
                    try:
                        extract_archive(root / archive, [i.member for i in group], work, extractor)
                    except (OSError, zipfile.BadZipFile) as error:
                        for item in group:
                            entries.append({"source": label, "path": item.path, "kind": item.kind,
                                            "error": f"archive unreadable: {error}"})
                        continue
                    tasks = [(item, work / item.member.replace(chr(92), "/")) for item in group]
                futures = []
                for item, path in tasks:
                    if not path.is_file():
                        entries.append({"source": label, "path": item.path, "kind": item.kind,
                                        "error": "could not be read from its archive"})
                        continue
                    futures.append(pool.submit(_run_isolated, item, path, settings))
                for future in futures:
                    entries.append(future.result())
                    done += 1
                    if done % 25 == 0 or done == len(items):
                        progress(100 * done / len(items), f"Exported {done} of {len(items)} files")
                if work is not None:
                    shutil.rmtree(work, ignore_errors=True)
    finally:
        shutil.rmtree(work_root, ignore_errors=True)
    entries.sort(key=lambda e: (e["kind"], e["source"], e["path"]))
    counts = {kind: sum(1 for e in entries if e["kind"] == kind and "outputs" in e) for kind in KINDS}
    errors = sum(1 for e in entries if "error" in e)
    index = {
        "schema": SCHEMA,
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "notice": NOTICE.replace("\n", " ").strip(),
        "options": {"kinds": sorted(kinds), "filter": args.filter, "include_dlc": args.include_dlc,
                    "include_v4": args.include_v4, "audio_format": args.audio_format},
        "sources": [{"label": s.label, "files": len(s.files)} for s in sources],
        "counts": counts,
        "errors": errors,
        "assets": entries,
    }
    (out / INDEX).write_text(json.dumps(index, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    progress(100, "Export finished")
    return {"result": "exported", "out": str(out), "assets": len(entries), "counts": counts,
            "errors": errors, "index": str(out / INDEX)}


def _run_isolated(item: Item, path: Path, settings: Settings) -> dict:
    try:
        return export_one(item, path, settings)
    except Exception as error:  # One bad asset never stops the export.
        return {"source": item.source, "path": item.path, "kind": item.kind,
                "error": f"{type(error).__name__}: {error}"}


def inventory(args: argparse.Namespace) -> dict:
    sources = gather_sources(args)
    items = plan(sources, set(KINDS), args.filter)
    counts = {kind: 0 for kind in KINDS}
    for item in items:
        counts[item.kind] += 1
    return {"result": "inventory", "sources": [{"label": s.label, "files": len(s.files)}
                                                 for s in sources],
            "counts": counts, "total": len(items)}


def add_parser(commands) -> None:
    parser = commands.add_parser("assets", help="export your own game files to standard formats")
    sub = parser.add_subparsers(dest="assets_command", required=True)
    for name, help_text in (("inventory", "count the assets each kind would export"),
                            ("export", "export assets to a folder you choose")):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--state-root")
        command.add_argument("--game-root")
        command.add_argument("--build-directory")
        command.add_argument("--filter")
        command.add_argument("--include-dlc", action="store_true")
        command.add_argument("--include-v4", action="store_true")
        command.add_argument("--json", action="store_true")
        if name == "export":
            command.add_argument("--out", required=True)
            command.add_argument("--kind", help="comma-separated: " + ",".join(KINDS))
            command.add_argument("--audio-format", default="wav", choices=AUDIO_FORMATS)
            command.add_argument("--ffmpeg")
            command.add_argument("--jobs", type=int)


def main(args: argparse.Namespace) -> int:
    try:
        result = export(args) if args.assets_command == "export" else inventory(args)
    except (AssetError, OSError) as error:
        if args.json:
            print(json.dumps({"result": "error", "error": str(error)}))
        else:
            print(f"error: {error}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result))
    else:
        if args.assets_command == "export":
            print(NOTICE)
        for key, value in result.items():
            print(f"{key}: {value}")
    return 0
