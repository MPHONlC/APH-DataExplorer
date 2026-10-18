# Copyright © 2026 @APHONlC. All rights reserved.
#
# No copying, modification, distribution, or sale without prior written permission.
# AI/ML ingestion and training are strictly prohibited (TDM opt-out).
#
# See LICENSE.md for full terms and maintenance exceptions.

import getpass
import glob
import os
import re
import time

HOME = os.path.expanduser("~")
APP_NAME = "APH Data Explorer"
APP_ID = "aph-data-explorer"
SETTINGS_ORG = "APH"
SETTINGS_NAME = "DataExplorer"
WINE_PREFIX = os.path.join(HOME, ".local/share/wineprefixes/esoextract")
INSTALL_NAMES = ("The Elder Scrolls Online", "The Elder Scrolls Online PTS")
ARCHIVE_ORDER = ("depot/eso.mnf", "game/client/game.mnf")
STEAM_ROOTS = (
    ".local/share/Steam",
    ".steam/steam",
    ".steam/root",
    ".var/app/com.valvesoftware.Steam/.local/share/Steam",
    ".var/app/com.valvesoftware.Steam/data/Steam",
    "snap/steam/common/.local/share/Steam",
)
PREFIX_PLACES = (
    ".wine",
    "Games/*",
    "Games/Heroic/Prefixes/*",
    "Games/Heroic/Prefixes/default/*",
    ".local/share/lutris/prefixes/*",
    ".local/share/bottles/bottles/*",
    ".var/app/com.usebottles.bottles/data/bottles/bottles/*",
    ".var/app/net.lutris.Lutris/data/lutris/prefixes/*",
    ".local/share/wineprefixes/*",
)
WINDOWS_GAME_DIRS = (
    "drive_c/Program Files (x86)/Zenimax Online",
    "drive_c/Program Files/Zenimax Online",
)
SKIP_DIRS = {".cache", ".git", "node_modules", "__pycache__", ".npm", ".cargo", ".rustup", "proc", "sys", "dev",
             "compatdata", "shadercache", "steamapps", "pfx", ".local", ".var", "snap", "Trash"}


def cache_dir():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(HOME, ".cache")
    path = os.path.join(base, APP_ID)
    os.makedirs(path, exist_ok=True)
    return path


def mount_roots():
    user = getpass.getuser()
    roots = []
    for pattern in ("/mnt/*", "/media/*", "/media/%s/*" % user, "/run/media/%s/*" % user, "/data", "/games"):
        roots.extend(p for p in glob.glob(pattern) if os.path.isdir(p))
    return roots


def steam_libraries():
    libs = []
    for rel in STEAM_ROOTS:
        root = os.path.join(HOME, rel)
        vdf = os.path.join(root, "steamapps/libraryfolders.vdf")
        if os.path.exists(vdf):
            try:
                text = open(vdf, encoding="utf-8", errors="replace").read()
                libs.extend(re.findall(r'"path"\s+"([^"]+)"', text))
            except OSError:
                pass
        if os.path.isdir(os.path.join(root, "steamapps")):
            libs.append(root)
    for root in mount_roots():
        for pattern in ("steamapps", "*/steamapps", "*/*/steamapps"):
            for hit in glob.glob(os.path.join(glob.escape(root), pattern)):
                libs.append(os.path.dirname(hit))
    seen, out = set(), []
    for lib in libs:
        real = os.path.realpath(lib)
        if real not in seen and os.path.isdir(real):
            seen.add(real)
            out.append(lib)
    return out


def is_install(path):
    return os.path.exists(os.path.join(path, "depot/eso.mnf")) or os.path.exists(os.path.join(path, "game/client/game.mnf"))


def detect_installs():
    libraries = steam_libraries()
    candidates = []
    for lib in libraries:
        for name in INSTALL_NAMES:
            candidates.append(os.path.join(lib, "steamapps/common/Zenimax Online", name))
    prefixes = []
    for place in PREFIX_PLACES:
        prefixes.extend(glob.glob(os.path.join(glob.escape(HOME), place)))
    for lib in libraries:
        prefixes.extend(glob.glob(os.path.join(glob.escape(lib), "steamapps/compatdata/*/pfx")))
    for prefix in prefixes:
        for games in WINDOWS_GAME_DIRS:
            for name in INSTALL_NAMES:
                candidates.append(os.path.join(prefix, games, name))
    for root in mount_roots():
        for pattern in ("Zenimax Online/*", "*/Zenimax Online/*", "*/*/Zenimax Online/*"):
            candidates.extend(glob.glob(os.path.join(glob.escape(root), pattern)))
    seen, found = set(), []
    for path in candidates:
        real = os.path.realpath(path)
        if real in seen or not is_install(path):
            continue
        seen.add(real)
        found.append(path)
    return found


def looks_like_dump(path):
    return os.path.isdir(os.path.join(path, "MAPS", "tiles")) or os.path.exists(os.path.join(path, "_raw", "game_mnf.txt"))


def find_tools(time_limit=10.0, max_depth=7):
    started = time.time()
    exe_dirs, dumps = [], []
    for top in [HOME] + mount_roots():
        base_depth = top.rstrip("/").count("/")
        for folder, dirs, files in os.walk(top):
            if time.time() - started > time_limit:
                return exe_dirs, dumps
            depth = folder.count("/") - base_depth
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not (depth == 0 and d.startswith("."))]
            if depth >= max_depth:
                dirs[:] = []
            if "EsoExtractData.exe" in files and folder not in exe_dirs:
                exe_dirs.append(folder)
                sibling = os.path.join(os.path.dirname(folder), "EXTRACTED")
                if looks_like_dump(sibling) and sibling not in dumps:
                    dumps.append(sibling)
            if looks_like_dump(folder):
                if folder not in dumps:
                    dumps.append(folder)
                dirs[:] = []
    return exe_dirs, dumps


def default_dump_folder(known):
    return known[0] if known else os.path.join(HOME, "ESO-Extracted", "EXTRACTED")


def archives_in(install):
    rels = []
    for path in glob.glob(os.path.join(glob.escape(install), "*", "*.mnf")) + glob.glob(os.path.join(glob.escape(install), "*", "*", "*.mnf")):
        rels.append(os.path.relpath(path, install))

    def order(rel):
        rel_unix = rel.replace(os.sep, "/")
        return (ARCHIVE_ORDER.index(rel_unix) if rel_unix in ARCHIVE_ORDER else len(ARCHIVE_ORDER), rel_unix)
    return sorted(set(rels), key=order)


def install_label(install):
    name = os.path.basename(install.rstrip("/")) or install
    if "/steamapps/" in install:
        where = install.split("/steamapps/")[0]
    elif "/drive_c/" in install:
        where = install.split("/drive_c/")[0]
    else:
        where = os.path.dirname(install.rstrip("/"))
    return f"{name}  ·  {where}"
