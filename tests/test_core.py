# Copyright © 2026 @APHONlC. All rights reserved.
#
# No copying, modification, distribution, or sale without prior written permission.
# AI/ML ingestion and training are strictly prohibited (TDM opt-out).
#
# See LICENSE.md for full terms and maintenance exceptions.

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dataexplorer import config, engine, runner, tables

HEADER = " Index ,    ID1    , FileIndex ,   Unk1    ,    Size   ,   ZSize   ,    Hash   ,   Offset  , ZTyp, Arch,  Unk2 , Filename\n"
ROWS = [
    (0, 0x01, 0x400, 0x200, 0, r"\esoui\app\app.txt"),
    (1, 0x02, 0x300, 0x100, 0, r"\esoui\app\globals\globals.lua"),
    (2, 0x03, 0x300, 0x100, 0, r"\esoui\art\auras\aura_mage01.dds"),
    (3, 0x04, 0x300, 0x100, 0, r"\esoui\art\auras\aura_warrior_01.dds"),
    (4, 0x05, 0x10000, 0x8000, 1, r"\art\maps\craglorn\rkundzelft_base_5.dds"),
    (5, 0x06, 0x10, 0x10, 1, ""),
    (6, 0x06, 0x10, 0x10, 1, ""),
    (7, 0x07, 0x20, 0x20, 2, ""),
]


def write_dump(path):
    with open(path, "w") as f:
        f.write(HEADER)
        for row, fidx, size, zsize, arch, name in ROWS:
            f.write(f"{row:7d}, 0x00000000, 0x{fidx:08X}, 0x00000000, 0x{size:08X}, 0x{zsize:08X}, 0x00000000, "
                    f"0x00000000, 0x00, 0x{arch:02X}, 0x0004, {name}\n")


def make_archive():
    tmp = tempfile.mkdtemp()
    dump = os.path.join(tmp, "mnf.txt")
    write_dump(dump)
    a = tables.Archive(tmp, "game/client/game.mnf")
    a._apply(tables.parse_mnf_dump(dump))
    return a


class TableTests(unittest.TestCase):
    def setUp(self):
        self.a = make_archive()

    def test_parse(self):
        a = self.a
        self.assertEqual(a.n, 8)
        self.assertEqual(a.names[2], "/esoui/art/auras/aura_mage01.dds")
        self.assertEqual(a.fidx[4], 5)
        self.assertEqual(a.size[4], 0x10000)
        self.assertEqual(a.arch[7], 2)
        self.assertNotIn(5, a.names)

    def test_tree(self):
        a = self.a
        top = [f.name for f in a.root.sorted_subs()]
        self.assertEqual(top, ["art", "esoui", "unmapped"])
        auras = a.find_folder("/esoui/art/auras/")
        self.assertEqual(list(auras.files), [2, 3])
        self.assertEqual(auras.path(), "/esoui/art/auras/")
        files, folders, size, zsize = a.stats(a.find_folder("/esoui/"))
        self.assertEqual((files, folders), (4, 4))
        self.assertEqual(size, 0x400 + 3 * 0x300)
        dats = [f.name for f in a.root.subs["\0unmapped"].sorted_subs()]
        self.assertEqual(dats, ["game0001.dat", "game0002.dat"])
        self.assertEqual(sorted(a.rows_below(a.root)), list(range(8)))

    def test_search(self):
        a = self.a
        self.assertEqual(list(a.search(".dds")), [4, 2, 3])
        self.assertEqual(list(a.search(r"\ESOUI\ART\\")), [2, 3])
        self.assertEqual(list(a.search("art/auras/")), [2, 3])
        self.assertEqual(list(a.search(r"aura_\w+_01", regex=True)), [3])
        self.assertEqual(list(a.search("#6")), [5, 6])
        self.assertEqual(list(a.search("")), [])

    def test_names(self):
        a = self.a
        self.assertEqual(a.native_name(2), r"\esoui\art\auras\aura_mage01.dds")
        self.assertEqual(a.twin_stem(4), os.path.join("001", "000004"))
        self.assertEqual(a.path(7), "/unmapped/game0002.dat/000007")
        self.assertEqual(a.fidx_count(6), 2)


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.a = make_archive()

    def covered(self, runs):
        out = []
        for r in runs:
            out.extend(r.rows)
        return sorted(out)

    def test_single_file_is_one_file_run(self):
        runs = runner.plan(self.a, [2])
        self.assertEqual([(r.kind, r.value) for r in runs], [("file", 3)])

    def test_whole_folder_is_one_match_run(self):
        rows = self.a.rows_below(self.a.find_folder("/esoui/art/auras/"))
        runs = runner.plan(self.a, rows)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].kind, "match")
        self.assertTrue(runs[0].value.startswith("\\esoui\\"))
        self.assertEqual(self.covered(runs), [2, 3])

    def test_everything_is_one_all_run(self):
        runs = runner.plan(self.a, range(self.a.n))
        self.assertEqual([r.kind for r in runs], ["all"])
        self.assertEqual(self.covered(runs), list(range(8)))

    def test_shared_file_index_runs_once(self):
        runs = runner.plan(self.a, [5, 6])
        self.assertEqual(self.covered(runs), [5, 6])
        self.assertEqual(sum(1 for r in runs if r.kind == "file"), len(runs))

    def test_every_row_lands_in_exactly_one_run(self):
        for selection in ([0, 2, 4, 7], [1, 3], list(range(8)), [4, 5]):
            runs = runner.plan(self.a, selection)
            self.assertEqual(self.covered(runs), sorted(selection), selection)

    def test_covers(self):
        run = runner.Run("match", "\\esoui\\art\\", [], 0, 0)
        self.assertTrue(runner.covers(self.a, run, 2))
        self.assertFalse(runner.covers(self.a, run, 0))
        self.assertFalse(runner.covers(self.a, run, 5))


class OutputTests(unittest.TestCase):
    def test_find_and_place(self):
        a = make_archive()
        tmp = tempfile.mkdtemp()
        named = os.path.join(tmp, "esoui", "art", "auras", "aura_mage01.dds")
        os.makedirs(os.path.dirname(named))
        os.makedirs(os.path.join(tmp, "001"))
        for path, data in ((named, b"x"), (os.path.join(tmp, "001", "000005.riff"), b"r"),
                           (os.path.join(tmp, "001", "000005.wav"), b"w")):
            with open(path, "wb") as f:
                f.write(data)
        found, twins = runner.find_output(tmp, a, 2)
        self.assertEqual(found, [named])
        found, twins = runner.find_output(tmp, a, 5)
        self.assertEqual(sorted(os.path.basename(t) for t in twins), ["000005.riff", "000005.wav"])
        dest = tempfile.mkdtemp()
        job = runner.Job(None, a, [], runner.Options(dest, preserve_parents=False, base="/esoui/art/"))
        self.assertEqual(job.target(2), os.path.join(dest, "auras", "aura_mage01.dds"))
        job.options.preserve_parents = True
        self.assertEqual(job.target(2), os.path.join(dest, "esoui", "art", "auras", "aura_mage01.dds"))
        self.assertEqual(job.target(5, ".wav"), os.path.join(dest, "unmapped", "game0001.dat", "000005.wav"))
        job._collect(tmp, [2, 5])
        self.assertTrue(os.path.exists(os.path.join(dest, "esoui", "art", "auras", "aura_mage01.dds")))
        self.assertTrue(os.path.exists(os.path.join(dest, "unmapped", "game0001.dat", "000005.wav")))
        self.assertEqual(job.missing, [])


class DetectTests(unittest.TestCase):
    def test_best_tool_folder(self):
        root = tempfile.mkdtemp()
        broken = os.path.join(root, "old", "EsoExtractData")
        good = os.path.join(root, "new", "EsoExtractData")
        for d, files in ((broken, ["EsoExtractData.exe"]), (good, ["EsoExtractData.exe", "oo2core_8_win64.dll"])):
            os.makedirs(d)
            for f in files:
                open(os.path.join(d, f), "w").close()
        os.makedirs(os.path.join(root, "new", "EXTRACTED", "MAPS", "tiles"))
        self.assertEqual(engine.best_tool_folder([broken, good]), good)
        self.assertEqual(engine.best_tool_folder([]), "")
        self.assertTrue(config.looks_like_dump(os.path.join(root, "new", "EXTRACTED")))
        self.assertFalse(config.looks_like_dump(os.path.join(root, "old")))

    def test_install_check_and_label(self):
        root = tempfile.mkdtemp()
        game = os.path.join(root, "steamapps", "common", "Zenimax Online", "The Elder Scrolls Online")
        os.makedirs(os.path.join(game, "depot"))
        self.assertFalse(config.is_install(game))
        open(os.path.join(game, "depot", "eso.mnf"), "w").close()
        self.assertTrue(config.is_install(game))
        self.assertEqual(config.install_label(game), f"The Elder Scrolls Online  ·  {root}")


@unittest.skipUnless(os.environ.get("APH_DE_LIVE"), "set APH_DE_LIVE=1 to read the installed game")
class LiveTests(unittest.TestCase):
    def test_extract_one_file(self):
        exe_dir = os.environ.get("APH_DE_TOOL") or engine.best_tool_folder(config.find_tools()[0])
        if not exe_dir:
            self.skipTest("EsoExtractData not found; set APH_DE_TOOL to its folder")
        tool = runner.Tool(exe_dir, engine.pick_wine(engine.find_wine_builds(), ""))
        self.assertIsNone(tool.problem())
        install = config.detect_installs()[0]
        a = tables.Archive(install, "game/client/game.mnf").load(tool)
        row = a.search("/esoui/app/globals/globals.lua")[0]
        dest = tempfile.mkdtemp()
        job = runner.Job(tool, a, runner.plan(a, [row]), runner.Options(dest))
        self.assertTrue(job.execute())
        path = os.path.join(dest, "esoui", "app", "globals", "globals.lua")
        self.assertTrue(os.path.exists(path))
        with open(path, "rb") as f:
            self.assertIn(b"zo_mixin", f.read())


if __name__ == "__main__":
    unittest.main()
