# Copyright © 2026 @APHONlC. All rights reserved.
#
# No copying, modification, distribution, or sale without prior written permission.
# AI/ML ingestion and training are strictly prohibited (TDM opt-out).
#
# See LICENSE.md for full terms and maintenance exceptions.

import os
import shutil
import subprocess
import threading
from array import array

from PySide6.QtCore import QObject, QSettings, QSize, Qt, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
                               QSpinBox, QVBoxLayout, QWidget)

from . import config, engine, tables
from .widgets import mono_font

ROLE_ROWS = Qt.UserRole + 10


def settings():
    return QSettings(config.SETTINGS_ORG, config.SETTINGS_NAME)


def form_layout(dialog, width=640):
    dialog.setMinimumWidth(width)
    form = QFormLayout(dialog)
    form.setContentsMargins(18, 16, 18, 14)
    form.setHorizontalSpacing(14)
    form.setVerticalSpacing(10)
    form.setRowWrapPolicy(QFormLayout.DontWrapRows)
    form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return form


def hint(text, wrap=True):
    label = QLabel(text)
    label.setWordWrap(wrap)
    label.setObjectName("hint")
    label.setMinimumWidth(360)
    return label


def fmt_seconds(s):
    s = int(round(s))
    if s < 60:
        return f"{max(1, s)} s"
    if s < 3600:
        return f"{s // 60} min {s % 60:02d} s"
    return f"{s // 3600} h {(s % 3600) // 60:02d} min"


class Finder(QObject):
    done = Signal(list, list)


class Bridge(QObject):
    progress = Signal(float, str)
    log = Signal(str)
    finished = Signal(bool, str)


class PathRow(QWidget):

    def __init__(self, path, title, directory=True, parent=None):
        super().__init__(parent)
        self.title, self.directory = title, directory
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit(path)
        btn = QPushButton("Choose…")
        btn.clicked.connect(self.choose)
        lay.addWidget(self.edit, 1)
        lay.addWidget(btn)

    def choose(self):
        if self.directory:
            path = QFileDialog.getExistingDirectory(self, self.title, self.edit.text())
        else:
            path, _ = QFileDialog.getOpenFileName(self, self.title, os.path.dirname(self.edit.text()))
        if path:
            self.edit.setText(path)

    def path(self):
        return os.path.expanduser(self.edit.text().strip())

    def minimumSizeHint(self):
        return QSize(super().minimumSizeHint().width(), self.sizeHint().height())


class FilterDialog(QDialog):

    def __init__(self, archives, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Queue files by name or extension")
        self.archives = [a for a in archives if a.loaded]
        form = form_layout(self)
        self.archive = QComboBox()
        for a in self.archives:
            self.archive.addItem(f"{a.label}  ({config.install_label(a.install)})", a)
        self.text = QLineEdit()
        self.text.setPlaceholderText(r"\art\maps\   or   art/icons/   or   aura_")
        self.ext = QLineEdit()
        self.ext.setPlaceholderText("dds, lua, xml… (empty: any)")
        self.count = QLabel()
        form.addRow("Archive", self.archive)
        form.addRow("Name contains", self.text)
        form.addRow("Extensions", self.ext)
        form.addRow("", self.count)
        form.addRow(hint("Slashes either way work; the archive stores names with backslashes and the match ignores case. "
                         "The files go into the queue, where you pick where to write them."))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Add to queue")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.ok = buttons.button(QDialogButtonBox.Ok)
        for w in (self.text, self.ext):
            w.textChanged.connect(self.refresh)
        self.archive.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def result_rows(self):
        a = self.archive.currentData()
        if a is None:
            return None, array("L"), None
        needle = self.text.text().strip()
        exts = {e.strip().lstrip(".").lower() for e in self.ext.text().split(",") if e.strip()}
        rows = a.search(needle) if needle else a.named
        if exts:
            rows = array("L", (r for r in rows if a.ext(r) in exts))
        native = needle.replace("/", "\\") if needle else None
        return a, rows, native

    def refresh(self):
        a, rows, _ = self.result_rows()
        size = sum(a.size[r] for r in rows) if a else 0
        self.count.setText(f"{len(rows):,} files, {tables.human_size(size)}")
        self.ok.setEnabled(len(rows) > 0)


class CommandDialog(QDialog):

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(780, 480)
        lay = QVBoxLayout(self)
        self.stage = QLabel()
        self.stage.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.logbox = QPlainTextEdit()
        self.logbox.setReadOnly(True)
        self.logbox.setFont(mono_font())
        self.logbox.setMaximumBlockCount(5000)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.Close).setEnabled(False)
        lay.addWidget(self.stage)
        lay.addWidget(self.bar)
        lay.addWidget(self.logbox, 1)
        lay.addWidget(self.buttons)
        self.bridge = Bridge()
        self.bridge.log.connect(self.logbox.appendPlainText)
        self.bridge.finished.connect(self._done)
        self.tool = None

    def run(self, tool, args, install=None, label=""):
        self.tool = tool
        self.stage.setText(label)
        def work():
            try:
                code = tool.run(args, on_line=self.bridge.log.emit, install=install)
                self.bridge.finished.emit(code == 0, "Done." if code == 0 else f"EsoExtractData stopped with exit code {code}.")
            except Exception as err:
                self.bridge.finished.emit(False, str(err))
        threading.Thread(target=work, daemon=True).start()

    def _done(self, ok, text):
        self.stage.setText(text)
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.buttons.button(QDialogButtonBox.Close).setEnabled(True)

    def reject(self):
        if not self.buttons.button(QDialogButtonBox.Close).isEnabled():
            if QMessageBox.question(self, self.windowTitle(), "Stop it?") != QMessageBox.Yes:
                return
            if self.tool:
                self.tool.kill()
        super().reject()


class MapsDialog(QDialog):
    def __init__(self, installs, extracted, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Map tiles only")
        form = form_layout(self, 680)
        self.install = QComboBox()
        for path in installs:
            self.install.addItem(config.install_label(path), path)
        self.root = PathRow(settings().value("maps/root", "") or config.default_dump_folder(extracted), "EXTRACTED folder")
        form.addRow("Game", self.install)
        form.addRow("EXTRACTED folder", self.root)
        form.addRow(hint("Every texture under \\art\\maps\\ in depot\\eso.mnf, as DDS and PNG, merged into "
                         "<EXTRACTED>/MAPS/tiles/<zone>/. Same as esoextractdata-linux.sh --maps; about half a minute "
                         "plus the PNG step."))
        b = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        b.button(QDialogButtonBox.Ok).setText("Extract map tiles")
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        form.addRow(b)


class FullDumpDialog(QDialog):
    def __init__(self, installs, extracted, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Everything, sorted")
        form = form_layout(self, 680)
        self.install = QComboBox()
        for path in installs:
            self.install.addItem(config.install_label(path), path)
        self.root = PathRow(settings().value("full/root", "") or config.default_dump_folder(extracted), "EXTRACTED folder")
        self.start = QLineEdit("0")
        form.addRow("Game", self.install)
        form.addRow("EXTRACTED folder", self.root)
        form.addRow("Resume depot at subfile", self.start)
        form.addRow(hint("Runs extract_all_linux.sh: both main archives, sorted by kind (MAPS, UI, GAMEDATA, TEXTURES, "
                         "MODELS, SHADERS, DATA, UNNAMED), textures to PNG and LANG files to CSV. It takes a couple of "
                         "hours and around 500 GB. It runs on its own, so closing this app does not stop it; its log "
                         "goes to <EXTRACTED>/extract_all.log."))
        b = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        b.button(QDialogButtonBox.Ok).setText("Start")
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        form.addRow(b)


def launch_full_dump(tool, install, root, start):
    os.makedirs(root, exist_ok=True)
    log_path = os.path.join(root, "extract_all.log")
    script = os.path.join(engine.ENGINE_DIR, "extract_all_linux.sh")
    with open(log_path, "ab") as log:
        subprocess.Popen(["bash", script, root, str(start)], cwd=engine.ENGINE_DIR, env=tool.env(install),
                         stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    return log_path


class LangDialog(QDialog):

    MODES = [
        ("LANG to CSV", "lang"),
        ("LANG to CSV, PO (Pootle) layout", "lang_po"),
        ("LANG to plain text", "lang_txt"),
        ("CSV back to LANG", "csv"),
        ("PO-layout CSV back to LANG", "csv_po"),
        ("Text + ID file back to LANG", "txt"),
        ("Compare two LANG/CSV/TXT files", "diff"),
    ]

    def __init__(self, tool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("LANG tools")
        self.tool = tool
        form = form_layout(self, 720)
        self.mode = QComboBox()
        for label, key in self.MODES:
            self.mode.addItem(label, key)
        self.first = PathRow("", "Input file", directory=False)
        self.second = PathRow("", "Second file", directory=False)
        self.second_label = QLabel("ID file")
        self.out = QLineEdit()
        self.out.setPlaceholderText("Output file (empty: next to the input)")
        form.addRow("Task", self.mode)
        form.addRow("Input", self.first)
        form.addRow(self.second_label, self.second)
        form.addRow("Output", self.out)
        b = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Close)
        b.button(QDialogButtonBox.Ok).setText("Run")
        b.accepted.connect(self.run)
        b.rejected.connect(self.reject)
        form.addRow(b)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self._mode_changed()

    def _mode_changed(self):
        key = self.mode.currentData()
        needs_second = key in ("txt", "diff")
        self.second.setVisible(needs_second)
        self.second_label.setVisible(needs_second)
        self.second_label.setText("ID file" if key == "txt" else "Compare with")
        self.out.setEnabled(key != "diff")

    def args(self):
        key = self.mode.currentData()
        a, b, out = self.first.path(), self.second.path(), self.out.text().strip()
        if key.startswith("lang"):
            args = ["-l", a]
            if key == "lang_po":
                args.append("-p")
            if key == "lang_txt":
                args.append("-t")
        elif key in ("csv", "csv_po"):
            args = ["-x", a] + (["-p"] if key == "csv_po" else [])
        elif key == "txt":
            args = ["-x", a, "-i", b, "-t"]
        else:
            return ["-d", a, b]
        if out:
            args += ["-o", os.path.expanduser(out)]
        return args

    def run(self):
        if not os.path.isfile(self.first.path()):
            QMessageBox.warning(self, "LANG tools", "Choose an input file.")
            return
        dlg = CommandDialog("LANG tools", self)
        dlg.run(self.tool, self.args(), label=self.mode.currentText())
        dlg.exec()


class SettingsDialog(QDialog):
    def __init__(self, installs, exe_dir, builds, build, extracted, cache_mb, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(780)
        self.resize(840, 800)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(12)
        g = QGroupBox("Game folders")
        gl = QVBoxLayout(g)
        self.list = QListWidget()
        self.list.setMinimumHeight(80)
        self.list.setMaximumHeight(140)
        for p in installs:
            self.list.addItem(p)
        row = QHBoxLayout()
        add = QPushButton("Add…")
        remove = QPushButton("Remove")
        detect = QPushButton("Find installs")
        detect.setToolTip("Steam libraries on every drive, Wine/Proton prefixes, Lutris, Heroic and Bottles")
        add.clicked.connect(self._add)
        remove.clicked.connect(lambda: [self.list.takeItem(self.list.row(i)) for i in self.list.selectedItems()])
        detect.clicked.connect(self._detect)
        for w in (add, remove, detect):
            row.addWidget(w)
        row.addStretch(1)
        gl.addWidget(self.list)
        gl.addLayout(row)
        lay.addWidget(g)

        t = QGroupBox("Engine")
        tv = QVBoxLayout(t)
        tl = QFormLayout()
        tv.addLayout(tl)
        tl.setHorizontalSpacing(14)
        tl.setVerticalSpacing(10)
        tl.setRowWrapPolicy(QFormLayout.DontWrapRows)
        self.exe = PathRow(exe_dir, "EsoExtractData folder")
        self.search = QPushButton("Search")
        self.search.setToolTip("Look through your home folder and other drives for EsoExtractData and extracted files")
        self.search.clicked.connect(self._search_tools)
        self.exe.layout().addWidget(self.search)
        tl.addRow("EsoExtractData folder", self.exe)
        self.wine = QComboBox()
        for b in builds:
            self.wine.addItem(f"{b.label}  ({b.wine})", b.wine)
        if build is not None:
            self.wine.setCurrentIndex(max(0, self.wine.findData(build.wine)))
        tl.addRow("Run it with", self.wine)
        tv.addWidget(hint(f"Wine uses the prefix {config.WINE_PREFIX}, Proton builds use esoextract-proton next to it.\n"
                          "EsoExtractData is downloaded separately from UESP; this app does not ship it.", wrap=False))
        lay.addWidget(t)

        e = QGroupBox("Already-extracted files (previewed at once, without EsoExtractData)")
        el = QVBoxLayout(e)
        self.extracted = QListWidget()
        self.extracted.setMinimumHeight(80)
        self.extracted.setMaximumHeight(140)
        for p in extracted:
            self.extracted.addItem(p)
        er = QHBoxLayout()
        eadd = QPushButton("Add…")
        eremove = QPushButton("Remove")
        eadd.clicked.connect(self._add_extracted)
        eremove.clicked.connect(lambda: [self.extracted.takeItem(self.extracted.row(i)) for i in self.extracted.selectedItems()])
        er.addWidget(eadd)
        er.addWidget(eremove)
        er.addStretch(1)
        el.addWidget(self.extracted)
        el.addLayout(er)
        el.addWidget(hint("Folders made by the full sorted dump, or by extracting here with the archive's folder paths kept.\n"
                          "A file is used only when it is newer than the archive and its size matches.\n"
                          "Files that are in none of these folders are read straight from the game archives.", wrap=False))
        lay.addWidget(e)

        c = QGroupBox("Preview cache")
        cl = QHBoxLayout(c)
        self.cache_label = QLabel()
        self.cache_label.setWordWrap(True)
        self.cache_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.cache_mb = QSpinBox()
        self.cache_mb.setRange(100, 100000)
        self.cache_mb.setSingleStep(250)
        self.cache_mb.setSuffix(" MB")
        self.cache_mb.setValue(int(cache_mb))
        clear = QPushButton("Clear previews")
        clear.clicked.connect(self._clear_previews)
        cl.addWidget(self.cache_label, 1)
        cl.addWidget(QLabel("Keep at most"))
        cl.addWidget(self.cache_mb)
        cl.addWidget(clear)
        lay.addWidget(c)
        b = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        lay.addWidget(b)
        self._cache_text()

    def _cache_text(self):
        from . import previews
        self.cache_label.setText(f"{previews.cache_root()}  ({tables.human_size(previews.cache_size())})")

    def _clear_previews(self):
        from . import previews
        shutil.rmtree(previews.cache_root(), ignore_errors=True)
        self._cache_text()

    def _add(self):
        path = QFileDialog.getExistingDirectory(self, "Game folder (the one with depot/ and game/)")
        if path:
            self.list.addItem(path)

    def _add_extracted(self):
        path = QFileDialog.getExistingDirectory(self, "Folder with extracted game files")
        if path:
            self.extracted.addItem(path)

    def _search_tools(self):
        self.search.setEnabled(False)
        self.search.setText("Searching…")
        self.finder = Finder()
        self.finder.done.connect(self._tools_found)
        threading.Thread(target=lambda: self.finder.done.emit(*map(list, config.find_tools())), daemon=True).start()

    def _tools_found(self, exe_dirs, dumps):
        self.search.setEnabled(True)
        self.search.setText("Search")
        best = engine.best_tool_folder(exe_dirs)
        if best and engine.exe_problem(self.exe.path()):
            self.exe.edit.setText(best)
        have = set(self.extracted_folders())
        for d in dumps:
            if d not in have:
                self.extracted.addItem(d)
        if not exe_dirs and not dumps:
            QMessageBox.information(self, "Search", "Nothing found. Choose the folders by hand.")

    def _detect(self):
        have = {self.list.item(i).text() for i in range(self.list.count())}
        for p in config.detect_installs():
            if p not in have:
                self.list.addItem(p)

    def installs(self):
        return [self.list.item(i).text() for i in range(self.list.count())]

    def extracted_folders(self):
        return [self.extracted.item(i).text() for i in range(self.extracted.count())]
