#!/usr/bin/env python3
# Copyright © 2026 @APHONlC. All rights reserved.
#
# No copying, modification, distribution, or sale without prior written permission.
# AI/ML ingestion and training are strictly prohibited (TDM opt-out).
#
# See LICENSE.md for full terms and maintenance exceptions.

import os
import sys
from multiprocessing import Pool

from PIL import Image


def convert(src):
    try:
        with Image.open(src) as im:
            im.save(src[:-4] + ".png")
        return None
    except Exception as err:
        return f"{src}: {err}"


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip())
        return 2
    root, force = sys.argv[1], "--force" in sys.argv
    todo, skipped = [], 0
    for folder, _, files in os.walk(root):
        for name in files:
            if not name.lower().endswith(".dds"):
                continue
            src = os.path.join(folder, name)
            dst = src[:-4] + ".png"
            if not force and os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
                skipped += 1
                continue
            todo.append(src)
    with Pool() as pool:
        errors = [e for e in pool.imap_unordered(convert, todo, chunksize=32) if e]
    for e in errors:
        print("failed: " + e, file=sys.stderr)
    print(f"converted {len(todo) - len(errors)}, already done {skipped}, failed {len(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
