# Copyright © 2026 @APHONlC. All rights reserved.
#
# No copying, modification, distribution, or sale without prior written permission.
# AI/ML ingestion and training are strictly prohibited (TDM opt-out).
#
# See LICENSE.md for full terms and maintenance exceptions.

import bisect
import hashlib
import os
import pickle
import re
import tempfile
from array import array

from . import config

CACHE_VERSION = 2


def human_size(n):
    for unit in ("B", "kB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"


def exact_size(n):
    return f"{human_size(n)} ({n:,} bytes)"


class Folder:
    __slots__ = ("name", "parent", "subs", "files", "kind", "arch", "uid", "pos", "_stats", "_order")

    def __init__(self, name, parent, kind="dir", arch=None):
        self.name = name
        self.parent = parent
        self.subs = {}
        self.files = array("L")
        self.kind = kind
        self.arch = arch
        self.uid = None
        self.pos = 0
        self._stats = None
        self._order = None

    def path(self):
        if self.kind in ("root", "unmapped", "dat"):
            return "/" if self.kind == "root" else ""
        parts = []
        f = self
        while f is not None and f.kind == "dir":
            parts.append(f.name)
            f = f.parent
        return "/" + "/".join(reversed(parts)) + "/"

    def label_path(self):
        if self.kind == "unmapped":
            return "/unmapped/"
        if self.kind == "dat":
            return f"/unmapped/{self.name}/"
        return self.path()

    def sorted_subs(self):
        if self._order is None:
            self._order = sorted(self.subs.values(), key=lambda f: (f.kind == "unmapped", f.name.lower()))
            for i, f in enumerate(self._order):
                f.pos = i
        return self._order


class Archive:

    def __init__(self, install, rel):
        self.install = install
        self.rel = rel
        self.mnf = os.path.join(install, rel)
        self.dat_prefix = os.path.splitext(os.path.basename(rel))[0]
        self.key = hashlib.sha1(self.mnf.encode()).hexdigest()[:16]
        self.loaded = False
        self.error = None
        self.n = 0
        self.fidx = self.size = self.zsize = array("L")
        self.arch = array("H")
        self.names = {}
        self.root = None
        self.named = array("L")
        self._lower = []
        self._folder_of = {}
        self._unmapped = {}
        self._fidx_sorted = None
        self._arch_totals = None

    @property
    def label(self):
        return self.rel.replace("/", "\\")


    def cache_file(self):
        st = os.stat(self.mnf)
        return os.path.join(config.cache_dir(), "tables", f"{self.key}-{st.st_size}-{int(st.st_mtime)}.pickle")

    def load(self, tool, log=None):
        cache = self.cache_file()
        data = None
        if os.path.exists(cache):
            try:
                with open(cache, "rb") as f:
                    data = pickle.load(f)
                if data.get("version") != CACHE_VERSION:
                    data = None
            except Exception:
                data = None
        if data is None:
            data = self._dump_and_parse(tool, log)
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            for old in os.listdir(os.path.dirname(cache)):
                if old.startswith(self.key + "-"):
                    try:
                        os.remove(os.path.join(os.path.dirname(cache), old))
                    except OSError:
                        pass
            tmp = cache + ".part"
            with open(tmp, "wb") as f:
                pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp, cache)
        self._apply(data)
        return self

    def _dump_and_parse(self, tool, log):
        with tempfile.TemporaryDirectory(prefix="aph-ab-") as tmp:
            out = os.path.join(tmp, "out")
            os.makedirs(out)
            mnf_txt = os.path.join(tmp, "mnf.txt")
            code = tool.run([self.mnf, out, "-k", "-m", mnf_txt], on_line=log)
            if code != 0 or not os.path.exists(mnf_txt):
                raise RuntimeError(f"EsoExtractData could not read {self.mnf} (exit {code})")
            return parse_mnf_dump(mnf_txt)

    def _apply(self, data):
        self.fidx, self.size, self.zsize, self.arch = data["fidx"], data["size"], data["zsize"], data["arch"]
        self.names = data["names"]
        self.n = len(self.fidx)
        self._build_tree()
        self.loaded = True

    def _build_tree(self):
        root = Folder("", None, "root")
        folder_of = {}
        for row, name in self.names.items():
            parts = name.strip("/").split("/")
            f = root
            for part in parts[:-1]:
                sub = f.subs.get(part)
                if sub is None:
                    sub = f.subs[part] = Folder(part, f)
                f = sub
            f.files.append(row)
            folder_of[row] = f
        unmapped = {}
        if len(self.names) < self.n:
            um = Folder("unmapped", root, "unmapped")
            root.subs["\0unmapped"] = um
            for row in range(self.n):
                if row in self.names:
                    continue
                a = self.arch[row]
                dat = unmapped.get(a)
                if dat is None:
                    dat = unmapped[a] = Folder(self.dat_name(a), um, "dat", a)
                    um.subs[dat.name] = dat
                dat.files.append(row)
        self.root = root
        self._folder_of = folder_of
        self._unmapped = unmapped
        self.named = array("L", sorted(self.names, key=lambda r: self.names[r].lower()))
        self._lower = [self.names[r].lower() for r in self.named]
        self._sort_folder_files(root)

    def _sort_folder_files(self, folder):
        stack = [folder]
        while stack:
            f = stack.pop()
            if f.kind == "dir" or f.kind == "root":
                if len(f.files) > 1:
                    f.files = array("L", sorted(f.files, key=lambda r: self.names[r].lower()))
            stack.extend(f.subs.values())


    def dat_name(self, a):
        return f"{self.dat_prefix}{a:04d}.dat"

    def path(self, row):
        name = self.names.get(row)
        if name is not None:
            return name
        return f"/unmapped/{self.dat_name(self.arch[row])}/{row:06d}"

    def base_name(self, row):
        name = self.names.get(row)
        if name is not None:
            return name.rsplit("/", 1)[-1]
        return f"{row:06d}  (file index {self.fidx[row]})"

    def ext(self, row):
        name = self.names.get(row)
        if name is None:
            return ""
        base = name.rsplit("/", 1)[-1]
        return base.rsplit(".", 1)[-1].lower() if "." in base else ""

    def folder_of(self, row):
        f = self._folder_of.get(row)
        if f is not None:
            return f
        return self._unmapped[self.arch[row]]

    def twin_stem(self, row):
        return os.path.join(f"{self.arch[row]:03d}", f"{row:06d}")

    def native_name(self, row):
        name = self.names.get(row)
        return name.replace("/", "\\") if name else None

    def fidx_count(self, value):
        if self._fidx_sorted is None:
            self._fidx_sorted = array("L", sorted(self.fidx))
        s = self._fidx_sorted
        return bisect.bisect_right(s, value) - bisect.bisect_left(s, value)

    def arch_totals(self):
        if self._arch_totals is None:
            totals = {}
            for row in range(self.n):
                a = self.arch[row]
                t = totals.get(a)
                if t is None:
                    totals[a] = [1, self.size[row]]
                else:
                    t[0] += 1
                    t[1] += self.size[row]
            self._arch_totals = totals
        return self._arch_totals


    def stats(self, folder):
        if folder._stats is None:
            files, folders, size, zsize = len(folder.files), 0, 0, 0
            for row in folder.files:
                size += self.size[row]
                zsize += self.zsize[row]
            for sub in folder.subs.values():
                s = self.stats(sub)
                files += s[0]
                folders += s[1] + 1
                size += s[2]
                zsize += s[3]
            folder._stats = (files, folders, size, zsize)
        return folder._stats

    def rows_below(self, folder):
        out = array("L")
        stack = [folder]
        while stack:
            f = stack.pop()
            out.extend(f.files)
            stack.extend(reversed(f.sorted_subs()))
        return out

    def find_folder(self, path):
        parts = [p for p in path.strip("/").split("/") if p]
        if parts and parts[0].lower() == "unmapped" and "\0unmapped" in self.root.subs:
            um = self.root.subs["\0unmapped"]
            if len(parts) == 1:
                return um
            return um.subs.get(parts[1]) if len(parts) == 2 else None
        f = self.root
        for part in path.strip("/").split("/"):
            if not part:
                continue
            f = f.subs.get(part) or next((s for s in f.subs.values() if s.name.lower() == part.lower()), None)
            if f is None:
                return None
        return f


    def search(self, query, regex=False, limit=None):
        q = query.strip()
        if not q:
            return array("L")
        if q.startswith("#") and q[1:].isdigit():
            num = int(q[1:])
            hits = set()
            if num < self.n:
                hits.add(num)
            for row in range(self.n):
                if self.fidx[row] == num:
                    hits.add(row)
            return array("L", sorted(hits))
        out = array("L")
        if regex:
            pattern = re.compile(q.replace("\\\\", "/"), re.IGNORECASE)
            for row, low in zip(self.named, self._lower):
                if pattern.search(low):
                    out.append(row)
                    if limit and len(out) >= limit:
                        break
        else:
            needle = re.sub("/+", "/", q.replace("\\", "/")).lower()
            for row, low in zip(self.named, self._lower):
                if needle in low:
                    out.append(row)
                    if limit and len(out) >= limit:
                        break
        return out


def parse_mnf_dump(path):
    fidx, size, zsize, arch = array("L"), array("L"), array("L"), array("H")
    names = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        next(f, None)
        for line in f:
            parts = line.rstrip("\r\n").split(",", 11)
            if len(parts) < 12:
                continue
            row = len(fidx)
            if int(parts[0]) != row:
                raise ValueError(f"{path}: row {row} is numbered {parts[0].strip()}")
            fidx.append(int(parts[2], 16))
            size.append(int(parts[4], 16))
            zsize.append(int(parts[5], 16))
            arch.append(int(parts[9], 16))
            name = parts[11].strip()
            if name:
                names[row] = name.replace("\\", "/") if name.startswith("\\") else "/" + name.replace("\\", "/")
    return {"version": CACHE_VERSION, "fidx": fidx, "size": size, "zsize": zsize, "arch": arch, "names": names}
