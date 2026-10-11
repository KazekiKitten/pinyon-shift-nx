import argparse
import csv
import io
import json
import sqlite3
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parent))
import pinyon_assets  # noqa: E402

from test_fh1_strings import table  # noqa: E402
from test_inspect_fh1_ui import make_xds  # noqa: E402


def dxt1_block(color):
    return struct.pack("<HHI", color, color, 0)


def io_zip(members):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def make_game(root):
    """A tiny synthetic game folder and the catalog that lists it."""
    files = {"default.xex": b"XEX2"}
    database = root / "gamedb.tmp"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE Data_Car (Id INTEGER, Name TEXT, Blob BLOB)")
    connection.execute("INSERT INTO Data_Car VALUES (1, 'Test car', x'0102')")
    connection.commit()
    connection.close()
    files["media/db/gamedb.slt"] = database.read_bytes()
    database.unlink()
    files["media/stringtables/EN.zip"] = io_zip(
        {"PauseMenu.str": table([(0x0010, "Resume"), (0x0011, "Neumáticos")])})
    files["media/ui/videos/intro.wmv"] = b"\x30\x26\xB2\x75 video"
    # A 4x4 DXT1 texture, tiled and 8-in-16 swapped as the 360 stores it.
    block = dxt1_block(0xF800)
    payload = bytearray(4096)
    payload[0:8] = bytes(block[i ^ 1] for i in range(8))
    files["media/ui/tick.xds"] = make_xds(4, 4, 18, 1, bytes(payload))
    files["media/cars/car.zip"] = io_zip({"car.carbin": b"\0\0\0\1\0\0\0\x11model"})
    files["media/audio/bank.fsb"] = b"FSB4"
    catalog = {"schema_version": 1, "files": []}
    for path, data in files.items():
        target = root / "game" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        catalog["files"].append({"guest_path": path, "size_bytes": len(data), "sha256": ""})
    (root / "catalog.json").write_text(json.dumps(catalog))
    return root / "game", root / "catalog.json"


def arguments(**values):
    defaults = dict(state_root=None, game_root=None, build_directory=None, filter=None,
                    include_dlc=False, include_v4=False, json=False, out=None, kind=None,
                    audio_format="wav", ffmpeg=None, jobs=1, assets_command="export")
    defaults.update(values)
    return argparse.Namespace(**defaults)


class AssetExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.game, catalog = make_game(self.root)
        patcher = mock.patch.object(pinyon_assets, "CATALOG", catalog)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_kinds_follow_the_file_names(self):
        self.assertEqual(pinyon_assets.kind_of("a/B.RMB.BIN"), "models")
        self.assertEqual(pinyon_assets.kind_of("x.xds"), "textures")
        self.assertEqual(pinyon_assets.kind_of("gamedb.slt"), "db")
        self.assertIsNone(pinyon_assets.kind_of("physics.bin"))

    def test_inventory_counts_loose_files_and_archive_members(self):
        result = pinyon_assets.inventory(arguments(game_root=str(self.game),
                                                   assets_command="inventory"))
        self.assertEqual(result["counts"], {"audio": 1, "textures": 1, "models": 1, "video": 1,
                                            "strings": 1, "db": 1})

    def test_export_writes_standard_formats_index_and_notice(self):
        out = self.root / "out"
        result = pinyon_assets.export(arguments(game_root=str(self.game), out=str(out),
                                                kind="textures,models,video,strings,db"))
        self.assertEqual(result["errors"], 0)
        index = json.loads((out / "assets.json").read_text(encoding="utf-8"))
        self.assertEqual(index["schema"], pinyon_assets.SCHEMA)
        self.assertIn("personal use", (out / "NOTICE.txt").read_text(encoding="utf-8"))
        # The texture: an untiled, byte-swapped DXT1 DDS and a PNG.
        dds = (out / "textures/base/media/ui/tick.dds").read_bytes()
        self.assertEqual(dds[:4], b"DDS ")
        self.assertEqual(dds[84:88], b"DXT1")
        self.assertEqual(dds[128:136], dxt1_block(0xF800))
        self.assertTrue((out / "textures/base/media/ui/tick.png").read_bytes()
                        .startswith(b"\x89PNG"))
        # Strings as JSON and CSV, with their keys.
        folder = out / "strings/base/media/stringtables/EN.zip"
        strings = json.loads((folder / "PauseMenu.json").read_text(encoding="utf-8"))
        self.assertEqual(strings[1], {"key": "0x0011", "text": "Neumáticos"})
        with (folder / "PauseMenu.csv").open(encoding="utf-8-sig", newline="") as stream:
            self.assertEqual(list(csv.reader(stream))[1], ["0x0010", "Resume"])
        # The database copied, and each table as CSV and JSON.
        self.assertTrue((out / "db/base/media/db/gamedb.slt").is_file())
        dump = json.loads((out / "db/base/media/db/gamedb.json").read_text(encoding="utf-8"))
        self.assertEqual(dump["Data_Car"], [{"Id": 1, "Name": "Test car", "Blob": "0102"}])
        self.assertTrue((out / "db/base/media/db/gamedb.tables/Data_Car.csv").is_file())
        # Video and models as stored.
        self.assertTrue((out / "video/base/media/ui/videos/intro.wmv").is_file())
        model = next(e for e in index["assets"] if e["kind"] == "models")
        self.assertIn("not decoded", model["note"])
        # Only the exports are left behind.
        self.assertFalse(any(p.name.startswith(".work-") for p in out.iterdir()))

    def test_filter_limits_the_export(self):
        out = self.root / "out"
        result = pinyon_assets.export(arguments(game_root=str(self.game), out=str(out),
                                                filter="*.str"))
        self.assertEqual(result["assets"], 1)
        self.assertEqual(result["counts"]["strings"], 1)

    def test_refuses_a_folder_that_holds_other_files(self):
        out = self.root / "out"
        out.mkdir()
        (out / "mine.txt").write_text("keep")
        with self.assertRaises(pinyon_assets.AssetError):
            pinyon_assets.export(arguments(game_root=str(self.game), out=str(out), kind="video"))
        self.assertEqual((out / "mine.txt").read_text(), "keep")

    def test_skips_files_that_differ_from_the_catalog(self):
        (self.game / "media/ui/videos/intro.wmv").write_bytes(b"edited, longer than before")
        result = pinyon_assets.inventory(arguments(game_root=str(self.game),
                                                   assets_command="inventory"))
        self.assertEqual(result["counts"]["video"], 0)

    def test_audio_needs_the_decoder(self):
        with mock.patch.object(pinyon_assets, "find_tool", return_value=None):
            with self.assertRaises(pinyon_assets.AssetError):
                pinyon_assets.export(arguments(game_root=str(self.game),
                                               out=str(self.root / "out"), kind="audio"))

    def test_unknown_kind_is_refused(self):
        with self.assertRaises(pinyon_assets.AssetError):
            pinyon_assets.export(arguments(game_root=str(self.game), out=str(self.root / "o"),
                                           kind="maps"))

    def test_dds_header_is_128_bytes(self):
        self.assertEqual(len(pinyon_assets.dds_bytes(4, 4, b"DXT5", b"")), 128)
        self.assertEqual(len(pinyon_assets.dds_bytes(2, 2, None, b"\0" * 16)), 144)


if __name__ == "__main__":
    unittest.main()
