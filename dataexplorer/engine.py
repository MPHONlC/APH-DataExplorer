# Copyright © 2026 @APHONlC. All rights reserved.
#
# No copying, modification, distribution, or sale without prior written permission.
# AI/ML ingestion and training are strictly prohibited (TDM opt-out).
#
# See LICENSE.md for full terms and maintenance exceptions.

import glob
import os
import shutil
import subprocess

from . import config

ENGINE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine")
WRAPPER = os.path.join(ENGINE_DIR, "esoextractdata-linux.sh")
UESP_PAGE = "https://en.uesp.net/wiki/ESOMod:EsoExtractData"
SIZE_SLACK = 1024

KIND_BY_TOP = {"esoui": "UI", "gamedata": "GAMEDATA", "granny": "MODELS", "shaders": "SHADERS"}
KIND_BY_EXT = {
    "dds": "TEXTURES", "png": "TEXTURES", "tga": "TEXTURES", "gr2": "MODELS",
    "wav": "SOUNDS", "ogg": "SOUNDS", "riff": "SOUNDS", "fsb": "SOUNDS", "bnk": "SOUNDS", "wem": "SOUNDS",
    "xv4": "VIDEO", "bik": "VIDEO", "bk2": "VIDEO", "ttf": "FONTS", "otf": "FONTS", "slug": "FONTS",
    "fx": "SHADERS", "fxh": "SHADERS", "ffx": "SHADERS", "hlsl": "SHADERS",
    "lua": "UI", "luac": "UI", "xml": "UI", "lang": "LANG", "csv": "LANG",
    "hkx": "ANIMATIONS", "psb2": "EFFECTS",
    "esoiddata": "DATA", "esofiledata": "DATA", "zosft": "DATA", "dat": "DATA", "txt": "DATA",
}


class WineBuild:
    def __init__(self, label, wine, kind):
        self.label, self.wine, self.kind = label, wine, kind

    @property
    def wineserver(self):
        if self.kind == "system":
            return shutil.which("wineserver") or "wineserver"
        return os.path.join(os.path.dirname(self.wine), "wineserver")

    @property
    def prefix(self):
        suffix = "" if self.kind == "system" else "-proton"
        return config.WINE_PREFIX + suffix

    def key(self):
        return self.wine


def find_wine_builds():
    builds = []
    system = shutil.which("wine")
    if system:
        builds.append(WineBuild("Wine (system)", system, "system"))
    seen = set()
    roots = []
    for lib in config.steam_libraries():
        roots.append(os.path.join(lib, "steamapps", "common"))
    for rel in config.STEAM_ROOTS:
        roots.append(os.path.join(config.HOME, rel, "compatibilitytools.d"))
    roots.append("/usr/share/steam/compatibilitytools.d")
    for root in roots:
        for wine in sorted(glob.glob(os.path.join(glob.escape(root), "*", "files", "bin", "wine"))):
            real = os.path.realpath(wine)
            if real in seen or not os.access(wine, os.X_OK):
                continue
            seen.add(real)
            name = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(wine))))
            if "proton" in name.lower() or "compatibilitytools.d" in wine:
                builds.append(WineBuild(name, wine, "proton"))
    return builds


def pick_wine(builds, wanted):
    for build in builds:
        if build.wine == wanted:
            return build
    return builds[0] if builds else None


def exe_problem(exe_dir):
    if not exe_dir or not os.path.isdir(exe_dir):
        return "missing_folder"
    if not os.path.exists(os.path.join(exe_dir, "EsoExtractData.exe")):
        return "missing_exe"
    if not os.path.exists(os.path.join(exe_dir, "oo2core_8_win64.dll")):
        return "missing_oodle"
    return None


class WarmWine:
    def __init__(self):
        self.build = None
        self.proc = None

    def start(self, build, seconds=900):
        self.stop()
        if build is None:
            return
        self.build = build
        os.makedirs(build.prefix, exist_ok=True)
        env = dict(os.environ, WINEPREFIX=build.prefix, WINEDEBUG="-all")
        try:
            self.proc = subprocess.Popen([build.wineserver, "-p%d" % seconds], env=env, stdin=subprocess.DEVNULL,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            self.proc = None

    def stop(self):
        if self.build is not None:
            env = dict(os.environ, WINEPREFIX=self.build.prefix)
            try:
                subprocess.run([self.build.wineserver, "-k"], env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            except (OSError, subprocess.TimeoutExpired):
                pass
        self.proc = None
        self.build = None


def extracted_candidates(root, archive, row):
    name = archive.names.get(row)
    if name:
        rel = name.strip("/")
        top = rel.split("/", 1)[0].lower()
        ext = rel.rsplit(".", 1)[-1].lower() if "." in rel else ""
        out = []
        if top in KIND_BY_TOP:
            out.append(os.path.join(root, KIND_BY_TOP[top], rel))
        elif rel.lower().startswith("art/maps/"):
            out.append(os.path.join(root, "MAPS", "tiles", rel[len("art/maps/"):]))
        else:
            out.append(os.path.join(root, KIND_BY_EXT.get(ext, "OTHER"), rel))
        out.append(os.path.join(root, rel))
        return out
    return unnamed_index(root, archive.arch[row]).get(row, [])


_unnamed = {}


def unnamed_index(root, arch):
    key = (root, arch)
    index = _unnamed.get(key)
    if index is None:
        index = {}
        base = os.path.join(root, "UNNAMED")
        kinds = os.listdir(base) if os.path.isdir(base) else []
        for kind in kinds:
            folder = os.path.join(base, kind, "%03d" % arch)
            if not os.path.isdir(folder):
                continue
            with os.scandir(folder) as it:
                for entry in it:
                    stem = entry.name.split(".", 1)[0]
                    if stem.isdigit():
                        index.setdefault(int(stem), []).append(entry.path)
        _unnamed[key] = index
    return index


def find_extracted(roots, archive, row):
    try:
        mnf_time = os.path.getmtime(archive.mnf)
    except OSError:
        return []
    expected = archive.size[row]
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for path in extracted_candidates(root, archive, row):
            try:
                st = os.stat(path)
            except OSError:
                continue
            if st.st_mtime < mnf_time:
                continue
            if 0 <= expected - st.st_size <= SIZE_SLACK:
                extra = []
                if path.lower().endswith(".riff"):
                    stem = os.path.splitext(path)[0]
                    extra = [p for p in (path + ".ogg", path + ".wav", stem + ".ogg", stem + ".wav") if os.path.exists(p)]
                return [path] + extra
    return []


def best_tool_folder(exe_dirs):
    def score(d):
        sibling = os.path.join(os.path.dirname(d), "EXTRACTED")
        try:
            mtime = os.path.getmtime(os.path.join(d, "EsoExtractData.exe"))
        except OSError:
            mtime = 0
        return (exe_problem(d) is None, config.looks_like_dump(sibling), mtime)
    return max(exe_dirs, key=score) if exe_dirs else ""
