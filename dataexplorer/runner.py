# Copyright © 2026 @APHONlC. All rights reserved.
#
# No copying, modification, distribution, or sale without prior written permission.
# AI/ML ingestion and training are strictly prohibited (TDM opt-out).
#
# See LICENSE.md for full terms and maintenance exceptions.

import glob
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import engine

RUN_BASE = 0.6
RUN_PER_ROW = 2.2e-6
WRITE_RATE = 25e6
PER_FILE = 2.3e-3
SUBFILE = re.compile(r"Subfile\s+(\d+)\s+of\s+(\d+)")


class Tool:
    def __init__(self, exe_dir, build=None):
        self.dir = exe_dir
        self.build = build
        self.wrapper = engine.WRAPPER
        self._procs = set()
        self._lock = threading.Lock()

    def problem(self):
        if self.build is None:
            return "Wine or Proton was not found"
        issue = engine.exe_problem(self.dir)
        if issue == "missing_folder":
            return "The EsoExtractData folder is not set"
        if issue == "missing_exe":
            return f"EsoExtractData.exe is not in {self.dir}"
        if issue == "missing_oodle":
            return f"oo2core_8_win64.dll is not in {self.dir}; unpack the whole EsoExtractData download there"
        if not os.path.exists(self.wrapper):
            return f"The engine script is missing ({self.wrapper})"
        return None

    def env(self, install=None):
        env = dict(os.environ)
        env["WINEDEBUG"] = "-all"
        env["ESOEXTRACT_DIR"] = self.dir or ""
        if self.build is not None:
            env["WINE"] = self.build.wine
            env["WINEPREFIX"] = self.build.prefix
        if install:
            env["ESO_DIR"] = install
        return env

    def run(self, args, on_line=None, install=None, cancel=None):
        proc = subprocess.Popen(["bash", self.wrapper] + list(args), cwd=engine.ENGINE_DIR, env=self.env(install),
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors="replace", start_new_session=True)
        with self._lock:
            self._procs.add(proc)
        try:
            for line in proc.stdout:
                if on_line:
                    on_line(line.rstrip("\n"))
                if cancel is not None and cancel.is_set():
                    self._stop(proc)
                    break
            return proc.wait()
        finally:
            with self._lock:
                self._procs.discard(proc)

    def _stop(self, proc):
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def kill(self, hard=True):
        with self._lock:
            procs = list(self._procs)
        for proc in procs:
            self._stop(proc)
        if hard and procs and self.build is not None:
            subprocess.run([self.build.wineserver, "-k"], env=self.env(), stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Run:

    def __init__(self, kind, value, rows, seconds, size):
        self.kind, self.value, self.rows, self.seconds, self.size = kind, value, rows, seconds, size

    def args(self):
        if self.kind == "match":
            return ["--matchfilename", self.value]
        if self.kind == "archive":
            return ["-a", str(self.value)]
        if self.kind == "file":
            return ["-f", str(self.value)]
        return []

    def describe(self):
        if self.kind == "all":
            return "everything in the archive"
        if self.kind == "match":
            return f"names containing {self.value}"
        if self.kind == "archive":
            return f"all of archive {self.value}"
        return f"file index {self.value}"


def run_overhead(archive):
    return RUN_BASE + RUN_PER_ROW * archive.n


def plan(archive, selected):
    selected = set(selected)
    if not selected:
        return []
    overhead = run_overhead(archive)
    inside, marked = {}, set()
    for row in selected:
        f = archive.folder_of(row)
        inside.setdefault(id(f), []).append(row)
        while f is not None and id(f) not in marked:
            marked.add(id(f))
            f = f.parent

    def file_runs(rows):
        by_fidx = {}
        for row in rows:
            by_fidx.setdefault(archive.fidx[row], []).append(row)
        runs = []
        for fidx, rws in by_fidx.items():
            sharing = max(archive.fidx_count(fidx), len(rws))
            own = sum(archive.size[r] for r in rws)
            size = own * sharing // len(rws)
            runs.append(Run("file", fidx, rws, overhead + size / WRITE_RATE + PER_FILE * sharing, size))
        return runs

    def whole(folder):
        if folder.kind in ("root", "dir"):
            files, _, size, _ = archive.stats(folder)
            if folder.kind == "root":
                return Run("all", None, [], overhead + size / WRITE_RATE + PER_FILE * files, size)
            return Run("match", folder.path().replace("/", "\\"), [], overhead + size / WRITE_RATE + PER_FILE * files, size)
        if folder.kind == "dat":
            count, size = archive.arch_totals().get(folder.arch, (0, 0))
            return Run("archive", folder.arch, [], overhead + size / WRITE_RATE + PER_FILE * count, size)
        return None

    def best(folder):
        runs = file_runs(inside.get(id(folder), []))
        for sub in folder.subs.values():
            if id(sub) in marked:
                runs.extend(best(sub))
        one = whole(folder)
        if one is not None and one.seconds <= sum(r.seconds for r in runs):
            return [one]
        return runs

    runs = best(archive.root)
    remaining = set(selected)
    for run in runs:
        if run.kind == "file":
            remaining.difference_update(run.rows)
    for run in runs:
        if run.kind != "file":
            run.rows = sorted(r for r in remaining if covers(archive, run, r))
            remaining.difference_update(run.rows)
    runs = [r for r in runs if r.rows]
    if remaining:
        runs.extend(file_runs(sorted(remaining)))
    return runs


def covers(archive, run, row):
    if run.kind == "all":
        return True
    if run.kind == "archive":
        return archive.arch[row] == run.value
    if run.kind == "match":
        name = archive.native_name(row)
        return name is not None and run.value.lower() in name.lower()
    if run.kind == "file":
        return archive.fidx[row] == run.value
    return False


def substring_plan(archive, needle, rows):
    rows = list(rows)
    size = sum(archive.size[r] for r in rows)
    return [Run("match", needle, rows, run_overhead(archive) + size / WRITE_RATE + PER_FILE * len(rows), size)]


def plan_seconds(runs):
    return sum(r.seconds for r in runs)


def find_output(tmp, archive, row):
    name = archive.names.get(row)
    found = []
    if name:
        path = os.path.join(tmp, name.strip("/").replace("/", os.sep))
        if os.path.exists(path):
            found.append(path)
    twins = glob.glob(os.path.join(glob.escape(os.path.join(tmp, archive.twin_stem(row))) + ".*"))
    return found, twins


def convert_dds(path):
    from PIL import Image
    try:
        with Image.open(path) as im:
            im.save(path[:-4] + ".png")
        return None
    except Exception as err:
        return f"{path}: {err}"


class Options:
    def __init__(self, dest, preserve_parents=True, base="/", png=False, keep_dds=True, lang_csv=False, keep_numbered=False):
        self.dest = dest
        self.preserve_parents = preserve_parents
        self.base = base
        self.png = png
        self.keep_dds = keep_dds
        self.lang_csv = lang_csv
        self.keep_numbered = keep_numbered


class Job:

    def __init__(self, tool, archive, runs, options, on_progress=None, on_log=None):
        self.tool, self.archive, self.runs, self.options = tool, archive, runs, options
        self.on_progress = on_progress or (lambda frac, text: None)
        self.on_log = on_log or (lambda line: None)
        self.cancel = threading.Event()
        self.written = []
        self.missing = []
        self.failed_conversions = []

    def stop(self):
        self.cancel.set()
        self.tool.kill()

    def target(self, row, src_ext=None):
        a, o = self.archive, self.options
        name = a.names.get(row)
        if name is None:
            ext = src_ext or ""
            return os.path.join(o.dest, "unmapped", a.dat_name(a.arch[row]), f"{row:06d}{ext}")
        rel = name
        if not o.preserve_parents and o.base and rel.lower().startswith(o.base.lower()):
            rel = rel[len(o.base):]
        return os.path.join(o.dest, rel.strip("/").replace("/", os.sep))

    def execute(self):
        a, o = self.archive, self.options
        os.makedirs(o.dest, exist_ok=True)
        total = plan_seconds(self.runs) or 1
        done = 0.0
        tmp = os.path.join(o.dest, ".aph-extract-tmp")
        for i, run in enumerate(self.runs, 1):
            if self.cancel.is_set():
                break
            shutil.rmtree(tmp, ignore_errors=True)
            os.makedirs(tmp)
            label = f"Run {i} of {len(self.runs)}: {run.describe()} ({len(run.rows):,} files)"
            self.on_log(label)
            start = time.time()

            def line(text, _start=start, _run=run, _done=done):
                m = SUBFILE.search(text)
                if m:
                    inside = int(m.group(1)) / max(1, int(m.group(2)))
                else:
                    if text.strip():
                        self.on_log("  " + text.strip())
                    inside = min(time.time() - _start, _run.seconds) / max(_run.seconds, 0.001)
                self.on_progress(min(0.98, (_done + min(1.0, inside) * _run.seconds) / total), label)

            self.on_progress(done / total, label)
            code = self.tool.run([a.mnf, tmp] + run.args() + ["--noparsegr2"], on_line=line, install=a.install, cancel=self.cancel)
            if self.cancel.is_set():
                break
            if code != 0:
                self.on_log(f"  EsoExtractData stopped with exit code {code}")
            self._collect(tmp, run.rows)
            done += run.seconds
            self.on_progress(done / total, label)
        shutil.rmtree(tmp, ignore_errors=True)
        if not self.cancel.is_set():
            self._convert()
        self.on_progress(1.0, "Cancelled" if self.cancel.is_set() else "Done")
        return not self.cancel.is_set()

    def _collect(self, tmp, rows):
        a, o = self.archive, self.options
        for row in rows:
            named, twins = find_output(tmp, a, row)
            if not named and not twins:
                self.missing.append(row)
                continue
            if named:
                dst = self.target(row)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                os.replace(named[0], dst)
                self.written.append(dst)
                if o.keep_numbered:
                    for twin in twins:
                        keep = os.path.join(o.dest, "numbered", os.path.relpath(twin, tmp))
                        os.makedirs(os.path.dirname(keep), exist_ok=True)
                        os.replace(twin, keep)
                continue
            if a.names.get(row):
                twin = min(twins, key=len)
                dst = self.target(row)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                os.replace(twin, dst)
                self.written.append(dst)
                continue
            for twin in twins:
                dst = self.target(row, os.path.splitext(twin)[1])
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                os.replace(twin, dst)
                self.written.append(dst)
        if self.missing:
            self.on_log(f"  {len(self.missing):,} files were not written by EsoExtractData so far")

    def _convert(self):
        o = self.options
        if o.png:
            dds = [p for p in self.written if p.lower().endswith(".dds")]
            if dds:
                self.on_log(f"Converting {len(dds):,} DDS files to PNG")
                with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
                    for n, err in enumerate(pool.map(convert_dds, dds), 1):
                        if err:
                            self.failed_conversions.append(err)
                        if n % 200 == 0 or n == len(dds):
                            self.on_progress(0.99, f"PNG {n:,} of {len(dds):,}")
                if not o.keep_dds:
                    failed = {e.split(": ", 1)[0] for e in self.failed_conversions}
                    for p in dds:
                        if p not in failed and os.path.exists(p[:-4] + ".png"):
                            os.remove(p)
        if o.lang_csv:
            for p in [p for p in self.written if p.lower().endswith(".lang")]:
                self.on_log(f"LANG to CSV: {os.path.basename(p)}")
                self.tool.run(["-l", p, "-o", p + ".csv"], on_line=lambda t: None)
        for err in self.failed_conversions:
            self.on_log("  PNG failed: " + err)


def find_other_rows(tmp, archive):
    rows = []
    for d in os.listdir(tmp):
        if not re.fullmatch(r"\d{3}", d) or not os.path.isdir(os.path.join(tmp, d)):
            continue
        for f in os.listdir(os.path.join(tmp, d)):
            stem = f.split(".", 1)[0]
            if stem.isdigit() and int(stem) < archive.n:
                rows.append(int(stem))
    return sorted(set(rows))
