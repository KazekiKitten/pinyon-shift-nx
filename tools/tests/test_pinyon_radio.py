import argparse
import json
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parent))
import pinyon_radio  # noqa: E402

from test_fh1_strings import table  # noqa: E402
from test_inspect_fh1_ui import make_xds  # noqa: E402


def arguments(state, command, **values):
    defaults = dict(state_root=str(state), game_root=None, json=True, radio_command=command,
                    slot=None, name=None, add=False, paths=[], png=None, clear=False, mode=None,
                    path=None, build_directory=None)
    defaults.update(values)
    return argparse.Namespace(**defaults)


def png(width, height, pixel):
    ui = pinyon_radio.ui_tools()
    return ui.encode_png(width, height, bytes(pixel) * (width * height))


class StoreTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.state = self.root / "state"
        self.music = self.root / "music"
        (self.music / "sub").mkdir(parents=True)
        (self.music / "a.mp3").write_bytes(b"x")
        (self.music / "sub" / "b.flac").write_bytes(b"x")
        (self.music / "cover.jpg").write_bytes(b"x")

    def run_command(self, command, **values):
        return pinyon_radio.run(arguments(self.state, command, **values))

    def test_stations_fill_the_free_slots_in_order(self):
        self.run_command("create", name="  Night   Drive ")
        result = self.run_command("create", name="Second", slot="3", add=True)
        self.assertEqual([(s["slot"], s["name"], s["mode"]) for s in result["stations"]],
                         [("Radio1", "Night Drive", "replace"), ("Radio3", "Second", "add")])
        self.assertEqual(result["free_slots"], ["Radio2"])
        self.assertEqual(result["stations"][1]["replaces"], "HORIZON ROCKS")
        self.run_command("create", name="Third")
        with self.assertRaises(pinyon_radio.RadioError):
            self.run_command("create", name="Fourth")
        with self.assertRaises(pinyon_radio.RadioError):
            self.run_command("create", name="x" * 41, slot="Radio2")

    def test_music_sources_logo_rename_mode_and_delete(self):
        self.run_command("create", name="Mine", slot="radio2")
        song = self.root / "single.wav"
        song.write_bytes(b"x")
        result = self.run_command("add", slot="2", paths=[str(self.music), str(song)])
        station = result["stations"][0]
        self.assertEqual(station["tracks"], 3)  # a.mp3, sub/b.flac and the single file
        self.assertTrue(result["out_of_date"])
        with self.assertRaises(pinyon_radio.RadioError):
            self.run_command("add", slot="2", paths=[str(self.root / "missing")])
        logo = self.root / "logo.png"
        logo.write_bytes(png(4, 2, (255, 0, 0, 255)))
        station = self.run_command("logo", slot="Radio2", png=str(logo))["stations"][0]
        self.assertEqual(station["logo"], str(logo.resolve()))
        (self.root / "bad.png").write_bytes(b"not a png")
        with self.assertRaises(pinyon_radio.RadioError):
            self.run_command("logo", slot="Radio2", png=str(self.root / "bad.png"))
        station = self.run_command("rename", slot="2", name="Renamed")["stations"][0]
        self.assertEqual(station["name"], "Renamed")
        station = self.run_command("mode", slot="2", mode="add")["stations"][0]
        self.assertEqual(station["mode"], "add")
        station = self.run_command("remove", slot="2", paths=[str(self.music)])["stations"][0]
        self.assertEqual(station["tracks"], 1)
        song.unlink()
        station = self.run_command("list")["stations"][0]
        self.assertEqual(station["missing"], [str(song.resolve())])
        self.assertEqual(self.run_command("delete", slot="2")["stations"], [])
        with self.assertRaises(pinyon_radio.RadioError):
            self.run_command("rename", slot="2", name="Gone")
        stored = json.loads((self.state / pinyon_radio.STORE).read_text(encoding="utf-8"))
        self.assertEqual(stored["schema"], pinyon_radio.SCHEMA)

    def test_build_writes_one_mod_and_enables_it(self):
        self.run_command("create", name="Mine", slot="1")
        self.run_command("create", name="Rock On", slot="3", add=True)
        self.run_command("add", slot="1", paths=[str(self.music)])
        self.run_command("add", slot="3", paths=[str(self.music / "a.mp3")])
        game = self.root / "game"
        strings = game / pinyon_radio.STRINGS
        strings.mkdir(parents=True)
        with zipfile.ZipFile(strings / "EN.zip", "w") as archive:
            archive.writestr("MyProfile.str", table([(0x7693, "RADIO STATION"),
                                                     (0xA29E, "HORIZON BASS ARENA"),
                                                     (0xA39E, "HORIZON ROCKS")]))
            archive.writestr("Tips.str", table([(0x0B3A, "HORIZON BASS ARENA"),
                                                (0xE484, "Old tip")]))
        calls = {}

        def fake_build(state, name, stations, game_root, ffmpeg, ffprobe, log, members):
            calls.update(name=name, stations=stations, members=members)
            mod = state / "mods" / name
            mod.mkdir(parents=True)
            (mod / ".pinyon-radio").write_text("built\n")
            return {"mod": str(mod), "tracks": 2, "stations": {s.slot: len(s.files) for s in stations}}

        builder = pinyon_radio.radio_builder()
        with mock.patch.object(builder, "build_stations", fake_build), \
                mock.patch.object(pinyon_radio, "find_extractor", return_value=Path("unused")), \
                mock.patch.object(pinyon_radio, "find_ffmpeg", return_value="ffmpeg"):
            result = self.run_command("build", game_root=str(game))
        self.assertEqual(result["result"], "built")
        self.assertEqual(calls["name"], "custom_radio")
        self.assertEqual([(s.slot, len(s.files), s.replace) for s in calls["stations"]],
                         [("Radio1", 2, True), ("Radio3", 1, False)])
        tools = pinyon_radio.string_tools()
        profile = dict(tools.parse(calls["members"]["media/StringTables/EN.zip/MyProfile.str"]))
        self.assertEqual(profile[0xA29E], "MINE")
        self.assertEqual(profile[0xA39E], "ROCK ON")
        self.assertEqual(profile[0x7693], "RADIO STATION")
        tips = dict(tools.parse(calls["members"]["media/StringTables/EN.zip/Tips.str"]))
        self.assertEqual(tips[0x0B3A], "MINE")
        self.assertIn("Mine plays music", tips[0xE484])
        config = (self.state / "config" / "pinyon_shift.toml").read_text(encoding="utf-8")
        self.assertIn('enabled_mods = "custom_radio"', config)
        self.assertFalse(self.run_command("list")["out_of_date"])

        # With every station deleted, build removes its mod and disables it.
        self.run_command("delete", slot="1")
        self.run_command("delete", slot="3")
        self.assertEqual(self.run_command("build", game_root=str(game))["result"], "removed")
        self.assertFalse((self.state / "mods" / "custom_radio").exists())
        config = (self.state / "config" / "pinyon_shift.toml").read_text(encoding="utf-8")
        self.assertIn('enabled_mods = ""', config)

    def test_build_refuses_a_station_without_music(self):
        self.run_command("create", name="Empty")
        with self.assertRaises(pinyon_radio.RadioError):
            self.run_command("build", game_root=str(self.root / "game"))


class LogoTests(unittest.TestCase):
    def test_reads_rgb_grey_and_palette_pngs(self):
        ui = pinyon_radio.ui_tools()
        rgba = ui.encode_png(1, 1, bytes((10, 20, 30, 40)))
        self.assertEqual(pinyon_radio.read_png(rgba), (1, 1, bytes((10, 20, 30, 40))))

        def chunk(kind, body):
            import zlib
            return (struct.pack(">I", len(body)) + kind + body
                    + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))

        def make(color, row, extra=b""):
            import zlib
            return (b"\x89PNG\r\n\x1a\n"
                    + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 1, 8, color, 0, 0, 0)) + extra
                    + chunk(b"IDAT", zlib.compress(b"\x00" + row)) + chunk(b"IEND", b""))

        self.assertEqual(pinyon_radio.read_png(make(2, bytes((1, 2, 3, 4, 5, 6))))[2],
                         bytes((1, 2, 3, 255, 4, 5, 6, 255)))
        self.assertEqual(pinyon_radio.read_png(make(0, bytes((7, 9))))[2],
                         bytes((7, 7, 7, 255, 9, 9, 9, 255)))
        palette = chunk(b"PLTE", bytes((1, 2, 3, 4, 5, 6))) + chunk(b"tRNS", bytes((0,)))
        self.assertEqual(pinyon_radio.read_png(make(3, bytes((0, 1)), palette))[2],
                         bytes((1, 2, 3, 0, 4, 5, 6, 255)))

    def test_fit_centres_inside_transparency(self):
        out = pinyon_radio.fit(2, 2, bytes((200, 100, 50, 255)) * 4, 4, 2)
        alphas = [out[4 * i + 3] for i in range(8)]
        self.assertEqual(alphas, [0, 255, 255, 0, 0, 255, 255, 0])
        self.assertEqual(out[4:8], bytes((200, 100, 50, 255)))

    def test_dxt5_block_round_trips(self):
        ui = pinyon_radio.ui_tools()
        texels = [(250, 10, 10, 255) if i % 2 else (10, 10, 250, 0) for i in range(16)]
        decoded = ui._decode_block(53, pinyon_radio.encode_bc3_block(texels))
        # Transparent texels keep only their alpha.
        for got, want in zip(decoded, texels):
            channels = range(4) if want[3] else [3]
            self.assertLessEqual(max(abs(got[c] - want[c]) for c in channels), 8)
        flat = ui._decode_block(53, pinyon_radio.encode_bc3_block([(128, 64, 32, 200)] * 16))
        self.assertTrue(all(max(abs(a - b) for a, b in zip(t, (128, 64, 32, 200))) <= 4 for t in flat))

    def test_logo_is_written_where_the_texture_reads_it(self):
        ui = pinyon_radio.ui_tools()
        stock = make_xds(8, 4, 53, 1, bytes(4096))
        encoded = pinyon_radio.encode_logo(stock, png(16, 8, (0, 200, 0, 255)))
        self.assertEqual(encoded[:ui.XDS_HEADER_SIZE], stock[:ui.XDS_HEADER_SIZE])
        header, rgba = ui.decode_xds(encoded)
        self.assertEqual((header["width"], header["height"]), (8, 4))
        self.assertTrue(all(abs(rgba[i + 1] - 200) <= 4 and rgba[i + 3] == 255
                            for i in range(0, len(rgba), 4)))
        with self.assertRaises(pinyon_radio.RadioError):
            pinyon_radio.encode_logo(make_xds(8, 4, 6, 1, bytes(4096)), png(1, 1, (0, 0, 0, 0)))


if __name__ == "__main__":
    unittest.main()
