#!/usr/bin/env python3
# Copyright © 2026 @APHONlC. All rights reserved.
#
# No copying, modification, distribution, or sale without prior written permission.
# AI/ML ingestion and training are strictly prohibited (TDM opt-out).
#
# See LICENSE.md for full terms and maintenance exceptions.

import os
import re
import sys
from collections import Counter

KIND_BY_EXT = {
    "dds": "TEXTURES", "png": "TEXTURES", "tga": "TEXTURES",
    "gr2": "MODELS",
    "wav": "SOUNDS", "ogg": "SOUNDS", "riff": "SOUNDS", "fsb": "SOUNDS", "bnk": "SOUNDS", "wem": "SOUNDS",
    "xv4": "VIDEO", "bik": "VIDEO", "bk2": "VIDEO",
    "ttf": "FONTS", "otf": "FONTS", "slug": "FONTS",
    "fx": "SHADERS", "fxh": "SHADERS", "ffx": "SHADERS", "hlsl": "SHADERS",
    "lua": "UI", "luac": "UI", "xml": "UI",
    "lang": "LANG", "csv": "LANG",
    "hkx": "ANIMATIONS", "psb2": "EFFECTS",
    "esoiddata": "DATA", "esofiledata": "DATA", "zosft": "DATA", "dat": "DATA", "txt": "DATA",
}
KIND_BY_TOP = {"esoui": "UI", "gamedata": "GAMEDATA", "granny": "MODELS", "shaders": "SHADERS"}
NUMBERED = re.compile(r"^\d{3}$")


def kind_for(rel):
    top = rel.split("/", 1)[0].lower()
    if top in KIND_BY_TOP:
        return KIND_BY_TOP[top]
    ext = rel.rsplit(".", 1)[-1].lower() if "." in rel else ""
    if rel.lower().startswith("art/maps/"):
        return "MAPS"
    return KIND_BY_EXT.get(ext, "OTHER")


def read_table(path, cols):
    rows = []
    with open(path, encoding="utf-8", errors="replace") as f:
        next(f)
        for line in f:
            parts = [p.strip() for p in line.rstrip("\n").split(",")]
            if len(parts) < cols:
                continue
            rows.append(parts)
    return rows


def main():
    root, name = sys.argv[1], sys.argv[2]
    dry = "--dry-run" in sys.argv
    raw = os.path.join(root, "_raw", name)
    mnf = read_table(os.path.join(root, "_raw", name + "_mnf.txt"), 12)
    zos = read_table(os.path.join(root, "_raw", name + "_zosft.txt"), 9)
    zos_name = {}
    for r in zos:
        fname = ",".join(r[8:]).strip().strip("'").replace("\\", "/").lstrip("/")
        if fname:
            zos_name[int(r[4], 16)] = fname
    by_index = {}
    for r in mnf:
        fname = ",".join(r[11:]).strip().replace("\\", "/").lstrip("/")
        file_index = int(r[2], 16)
        by_index[(int(r[9], 16), int(r[0]))] = fname or zos_name.get(file_index, "")

    stats = Counter()
    moves = []
    for dirpath, dirnames, filenames in os.walk(raw):
        rel_dir = os.path.relpath(dirpath, raw).replace(os.sep, "/")
        top = rel_dir.split("/", 1)[0]
        numbered = bool(NUMBERED.match(top))
        for fn in filenames:
            path = os.path.join(dirpath, fn)
            rel = fn if rel_dir == "." else rel_dir + "/" + fn
            if numbered:
                stem, _, rest = fn.partition(".")
                ext = rest.rsplit(".", 1)[-1]
                try:
                    key = (int(top), int(stem))
                except ValueError:
                    key = None
                named = by_index.get(key) if key else ""
                twin = os.path.join(raw, named) if named else None
                if twin and os.path.exists(twin) and os.path.getsize(twin) == os.path.getsize(path):
                    stats["numbered duplicate removed"] += 1
                    moves.append((path, None))
                    continue
                kind = KIND_BY_EXT.get(ext.lower(), "OTHER")
                stats["unnamed " + kind] += 1
                moves.append((path, os.path.join(root, "UNNAMED", kind, top, fn)))
                continue
            kind = kind_for(rel)
            if kind == "MAPS":
                sorted_copy = os.path.join(root, "MAPS", "tiles", rel[len("art/maps/"):])
                if os.path.exists(sorted_copy) and os.path.getsize(sorted_copy) == os.path.getsize(path):
                    stats["map texture already in MAPS"] += 1
                    moves.append((path, None))
                    continue
                moves.append((path, sorted_copy))
            else:
                moves.append((path, os.path.join(root, kind, rel)))
            stats["named " + kind] += 1

    for key in sorted(stats):
        print("%-34s %d" % (key, stats[key]))
    if dry:
        return
    for src, dst in moves:
        if dst is None:
            os.remove(src)
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.exists(dst):
            if os.path.getsize(dst) == os.path.getsize(src):
                os.remove(src)
                continue
            base, dot, ext = dst.rpartition(".")
            dst = base + "." + name + dot + ext
        os.replace(src, dst)
    for dirpath, dirnames, filenames in os.walk(raw, topdown=False):
        if not os.listdir(dirpath):
            os.rmdir(dirpath)
    print("done")


if __name__ == "__main__":
    main()
