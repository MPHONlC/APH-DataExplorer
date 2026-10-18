# Copyright © 2026 @APHONlC. All rights reserved.
#
# No copying, modification, distribution, or sale without prior written permission.
# AI/ML ingestion and training are strictly prohibited (TDM opt-out).
#
# See LICENSE.md for full terms and maintenance exceptions.

import os
import shutil
import threading
import time

from . import config, engine, runner

PREFETCH_SECONDS = 25
NEIGHBOURS = 6
PRUNE_EVERY = 20


def cache_root():
    return os.path.join(config.cache_dir(), "preview")


def row_dir(archive, row):
    return os.path.join(cache_root(), archive.key, str(row))


def cached(archive, row):
    base = row_dir(archive, row)
    if not os.path.isdir(base):
        return []
    named, twins = runner.find_output(base, archive, row)
    hits = named + twins
    if hits:
        try:
            os.utime(base)
        except OSError:
            pass
    return hits


def place(tmp, archive, row):
    named, twins = runner.find_output(tmp, archive, row)
    if not named and not twins:
        return False
    base = row_dir(archive, row)
    shutil.rmtree(base, ignore_errors=True)
    for path in named + twins:
        rel = os.path.relpath(path, tmp)
        dst = os.path.join(base, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.replace(path, dst)
    return True


def cache_size():
    total = 0
    for d, _, files in os.walk(cache_root()):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(d, f))
            except OSError:
                pass
    return total


def prune(limit_bytes):
    root = cache_root()
    if not os.path.isdir(root):
        return
    entries, total = [], 0
    for key in os.listdir(root):
        for row in os.listdir(os.path.join(root, key)):
            path = os.path.join(root, key, row)
            size = 0
            for d, _, files in os.walk(path):
                for f in files:
                    try:
                        size += os.path.getsize(os.path.join(d, f))
                    except OSError:
                        pass
            entries.append((os.path.getmtime(path), size, path))
            total += size
    entries.sort()
    for _, size, path in entries:
        if total <= limit_bytes:
            break
        shutil.rmtree(path, ignore_errors=True)
        total -= size


class PreviewService:
    def __init__(self, make_tool, extracted_roots, on_ready, on_failed, on_status, limit_bytes):
        self.make_tool = make_tool
        self.extracted_roots = extracted_roots
        self.on_ready, self.on_failed, self.on_status = on_ready, on_failed, on_status
        self.limit_bytes = limit_bytes
        self.cv = threading.Condition()
        self.wanted = None
        self.background = []
        self.fetch_tool = None
        self.prefetch_tool = None
        self.fetches = 0
        threading.Thread(target=self._loop, daemon=True).start()

    def reconfigure(self):
        with self.cv:
            self.fetch_tool = None
            self.prefetch_tool = None

    def lookup(self, archive, row, roots=None):
        hits = engine.find_extracted(self.extracted_roots() if roots is None else roots, archive, row)
        if hits:
            return hits, "extracted"
        hits = cached(archive, row)
        if hits:
            return hits, "cache"
        return [], None

    def request(self, archive, row, lang_csv=False):
        hits, source = self.lookup(archive, row)
        if hits and not lang_csv:
            self.on_ready(archive, row, hits, source)
            return True
        with self.cv:
            self.wanted = (archive, row, lang_csv)
            if self.prefetch_tool is not None:
                self.prefetch_tool.kill(hard=False)
            self.cv.notify()
        return False

    def prefetch_folder(self, archive, folder):
        with self.cv:
            self.background = [("decide", archive, folder, None)]
            self.cv.notify()

    def prefetch_rows(self, archive, rows):
        with self.cv:
            self.background = [("rows", archive, None, list(rows))]
            self.cv.notify()

    def _missing(self, archive, rows, limit=None):
        out = []
        roots = [r for r in self.extracted_roots() if r and os.path.isdir(r)]
        for r in rows:
            with self.cv:
                if self.wanted is not None:
                    return None
            if not self.lookup(archive, r, roots)[0]:
                out.append(r)
                if limit and len(out) >= limit:
                    break
        return out

    def _decide(self, tool, archive, folder):
        files, _, size, _ = archive.stats(folder)
        seconds = runner.run_overhead(archive) + size / runner.WRITE_RATE + runner.PER_FILE * files
        if folder.kind == "dir" and seconds <= PREFETCH_SECONDS:
            missing = self._missing(archive, archive.rows_below(folder))
            if missing:
                self._prefetch_folder(tool, archive, folder, missing)
        else:
            self._prefetch_rows(tool, archive, list(folder.files[:NEIGHBOURS * 4]))

    def _tools(self):
        if self.fetch_tool is None:
            self.fetch_tool = self.make_tool()
        if self.prefetch_tool is None:
            self.prefetch_tool = self.make_tool()
        return self.fetch_tool, self.prefetch_tool

    def _loop(self):
        while True:
            with self.cv:
                while self.wanted is None and not self.background:
                    self.cv.wait()
                fetch_tool, prefetch_tool = self._tools()
                if self.wanted is not None:
                    task, self.wanted = ("fetch",) + self.wanted, None
                else:
                    task = self.background.pop(0)
            try:
                if task[0] == "fetch":
                    self._fetch(fetch_tool, *task[1:])
                elif task[0] == "decide":
                    self._decide(prefetch_tool, task[1], task[2])
                else:
                    self._prefetch_rows(prefetch_tool, task[1], task[3])
            except Exception as err:
                if task[0] == "fetch":
                    self.on_failed(task[1], task[2], f"Could not read this file: {err}")
            self.fetches += 1
            if self.fetches % PRUNE_EVERY == 0:
                prune(self.limit_bytes())

    def _pull_one(self, tool, archive, row):
        tmp = os.path.join(cache_root(), ".tmp-%d" % threading.get_ident())
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)
        try:
            tool.run([archive.mnf, tmp, "-f", str(archive.fidx[row]), "--noparsegr2"], install=archive.install)
            place(tmp, archive, row)
            for other in runner.find_other_rows(tmp, archive):
                place(tmp, archive, other)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return cached(archive, row)

    def _fetch(self, tool, archive, row, lang_csv):
        hits, source = self.lookup(archive, row)
        if not hits:
            started = time.time()
            hits = self._pull_one(tool, archive, row)
            source = "engine %.1f s" % (time.time() - started)
        if not hits:
            self.on_failed(archive, row, "EsoExtractData did not write this file.")
            return
        if lang_csv:
            csv = os.path.join(row_dir(archive, row), os.path.basename(hits[0]) + ".csv")
            if not os.path.exists(csv):
                tool.run(["-l", hits[0], "-o", csv], install=archive.install)
            if os.path.exists(csv):
                hits, source = [csv], "LANG as CSV"
        self.on_ready(archive, row, hits, source)

    def _prefetch_folder(self, tool, archive, folder, rows):
        label = folder.label_path()
        self.on_status(f"Prefetching {label} ({len(rows):,} files)")
        tmp = os.path.join(cache_root(), ".prefetch")
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)
        try:
            code = tool.run([archive.mnf, tmp, "--matchfilename", folder.path().replace("/", "\\"), "--noparsegr2"],
                            install=archive.install)
            placed = sum(1 for row in rows if place(tmp, archive, row))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.on_status(f"{label}: {placed:,} files ready to preview" if code == 0 else "")

    def _prefetch_rows(self, tool, archive, rows):
        missing = self._missing(archive, rows, NEIGHBOURS)
        for row in missing or []:
            with self.cv:
                if self.wanted is not None or self.background:
                    return
            self._pull_one(tool, archive, row)
