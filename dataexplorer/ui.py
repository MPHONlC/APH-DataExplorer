# Copyright © 2026 @APHONlC. All rights reserved.
#
# No copying, modification, distribution, or sale without prior written permission.
# AI/ML ingestion and training are strictly prohibited (TDM opt-out).
#
# See LICENSE.md for full terms and maintenance exceptions.

import os
import shutil
import threading
from array import array

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QToolButton, QVBoxLayout)

from . import config, engine, runner, tables
from .dialogs import Bridge, PathRow, fmt_seconds, settings
from .widgets import Preview, mono_font

ROLE_DATA = Qt.UserRole + 20


def section(text):
    label = QLabel(text)
    label.setObjectName("sectionLabel")
    return label


class HeaderBar(QFrame):
    searchChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("header")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(10)
        title = QLabel("Data Explorer")
        title.setObjectName("appTitle")
        self.query = QLineEdit()
        self.query.setObjectName("bigSearch")
        self.query.setPlaceholderText("Search names  ·  .dds   art/icons/   aura_   #12345")
        self.query.setClearButtonEnabled(True)
        self.query.setMinimumWidth(320)
        self.scope = QComboBox()
        self.scope.addItem("This archive", "one")
        self.scope.addItem("Every archive", "all")
        self.regex = QCheckBox("Regex")
        self.menu_button = QToolButton()
        self.menu_button.setObjectName("menuButton")
        self.menu_button.setText("Menu")
        self.menu_button.setPopupMode(QToolButton.InstantPopup)
        lay.addWidget(title)
        lay.addSpacing(16)
        lay.addWidget(self.query, 1)
        lay.addWidget(self.scope)
        lay.addWidget(self.regex)
        lay.addWidget(self.menu_button)
        self.query.textChanged.connect(lambda _: self.searchChanged.emit())
        self.scope.currentIndexChanged.connect(lambda _: self.searchChanged.emit())
        self.regex.toggled.connect(lambda _: self.searchChanged.emit())


class ArchiveStrip(QFrame):
    archiveChosen = Signal(object)
    installChosen = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("strip")
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(14, 6, 14, 6)
        self.lay.setSpacing(6)
        self.install = QComboBox()
        self.install.currentIndexChanged.connect(self.installChosen.emit)
        self.lay.addWidget(self.install)
        self.lay.addSpacing(8)
        self.chips = []
        self.lay.addStretch(1)

    def set_installs(self, installs):
        self.install.blockSignals(True)
        self.install.clear()
        for inst in installs:
            self.install.addItem(inst.label, inst)
        self.install.blockSignals(False)

    def set_archives(self, archives, current):
        for chip in self.chips:
            chip.deleteLater()
        self.chips = []
        for a in archives:
            chip = QToolButton()
            chip.setProperty("chip", True)
            chip.setCheckable(True)
            chip.setChecked(a is current)
            chip.setText(self.chip_text(a))
            chip.setToolTip(a.mnf)
            chip.clicked.connect(lambda _=False, arc=a: self.archiveChosen.emit(arc))
            self.lay.insertWidget(self.lay.count() - 1, chip)
            self.chips.append(chip)
        self._archives = archives

    def chip_text(self, a):
        name = a.rel.replace(os.sep, "/").split("/")[-1].replace(".mnf", "")
        if not a.loaded:
            return f"{name}  ·  …"
        return f"{name}  ·  {a.n:,}"

    def refresh(self, current):
        for chip, a in zip(self.chips, getattr(self, "_archives", [])):
            chip.setText(self.chip_text(a))
            chip.setChecked(a is current)
            chip.setMinimumWidth(chip.sizeHint().width())


class Breadcrumb(QFrame):
    folderChosen = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("breadcrumb")
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(8, 4, 8, 4)
        self.lay.setSpacing(2)

    def set_path(self, archive, folder, text=None):
        while self.lay.count():
            w = self.lay.takeAt(0).widget()
            if w:
                w.hide()
                w.deleteLater()
        if text is not None:
            label = QLabel(text)
            label.setObjectName("crumbBanner")
            self.lay.addWidget(label)
            self.lay.addStretch(1)
            return
        chain = []
        f = folder
        while f is not None:
            chain.append(f)
            f = f.parent
        for i, f in enumerate(reversed(chain)):
            if i:
                sep = QLabel("›")
                sep.setObjectName("crumbSep")
                self.lay.addWidget(sep)
            b = QToolButton()
            b.setObjectName("crumb")
            b.setText(archive.dat_prefix if f.parent is None else ("unmapped" if f.kind == "unmapped" else f.name))
            b.setAutoRaise(True)
            b.clicked.connect(lambda _=False, target=f: self.folderChosen.emit(target))
            self.lay.addWidget(b)
        self.lay.addStretch(1)


class Inspector(QFrame):
    addToQueue = Signal(object, object)
    extractNow = Signal(object, object)
    langRequested = Signal(object, int)
    pinFolder = Signal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("inspector")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)
        self.name = QLabel("Nothing selected")
        self.name.setObjectName("inspectorName")
        self.name.setWordWrap(True)
        self.name.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.badge = QLabel("")
        self.badge.setObjectName("badge")
        self.preview = Preview()
        self.preview.setMinimumHeight(260)
        self.props = QGridLayout()
        self.props.setHorizontalSpacing(12)
        self.props.setVerticalSpacing(3)
        self.props.setColumnStretch(1, 1)
        self._prop_rows = []
        self.actions = QHBoxLayout()
        self.actions.setSpacing(6)
        self.buttons = {}
        for key, text in (("queue", "Add to queue"), ("extract", "Extract now…"), ("open", "Open"),
                          ("save", "Save image…"), ("copy", "Copy path"), ("lang", "LANG → CSV"), ("pin", "Pin folder")):
            b = QPushButton(text)
            b.setObjectName("action")
            b.setProperty("accent", key == "queue")
            self.actions.addWidget(b)
            self.buttons[key] = b
        self.actions.addStretch(1)
        self.buttons["queue"].clicked.connect(lambda: self.current and self.addToQueue.emit(*self.current))
        self.buttons["extract"].clicked.connect(lambda: self.current and self.extractNow.emit(*self.current))
        self.buttons["open"].clicked.connect(self.open_external)
        self.buttons["save"].clicked.connect(self.save_image)
        self.buttons["copy"].clicked.connect(self.copy_path)
        self.buttons["lang"].clicked.connect(lambda: self.current and self.langRequested.emit(*self.current[1]))
        self.buttons["pin"].clicked.connect(lambda: self.current and self.pinFolder.emit(*self.current[1]))
        head = QHBoxLayout()
        head.addWidget(self.name, 1)
        head.addWidget(self.badge, 0, Qt.AlignTop)
        lay.addLayout(head)
        lay.addWidget(self.preview, 1)
        lay.addLayout(self.props)
        lay.addLayout(self.actions)
        self.current = None
        self.show_nothing()

    def _set_props(self, rows):
        for widgets in self._prop_rows:
            for w in widgets:
                w.hide()
        for i, (key, value) in enumerate(rows):
            if i >= len(self._prop_rows):
                k = QLabel()
                k.setObjectName("propKey")
                v = QLabel()
                v.setObjectName("propValue")
                v.setTextInteractionFlags(Qt.TextSelectableByMouse)
                v.setWordWrap(True)
                self.props.addWidget(k, i, 0, Qt.AlignTop)
                self.props.addWidget(v, i, 1)
                self._prop_rows.append((k, v))
            k, v = self._prop_rows[i]
            k.setText(key)
            v.setText(value)
            k.show()
            v.show()

    def _buttons(self, visible):
        for key, b in self.buttons.items():
            b.setVisible(key in visible)

    def show_nothing(self):
        self.current = None
        self.name.setText("Nothing selected")
        self.badge.setText("")
        self.preview.show_message("Pick a folder or a file.\n\nDouble-click a folder to open it, press Backspace to go up.\n"
                                  "Add folders, files or search results to the queue below, then extract them together.")
        self._set_props([])
        self._buttons(())

    def show_folder(self, archive, folder):
        self.current = ("folder", (archive, folder))
        files, folders, size, zsize = archive.stats(folder)
        self.name.setText(folder.label_path() if folder.parent else archive.label)
        self.badge.setText("folder")
        counts = {}
        if files <= 200000:
            for row in archive.rows_below(folder):
                e = archive.ext(row) or "unnamed"
                counts[e] = counts.get(e, 0) + 1
        top = sorted(counts.items(), key=lambda kv: -kv[1])[:10]
        lines = [f"{files:,} files in {folders:,} folders", f"{tables.human_size(size)} unpacked, {tables.human_size(zsize)} packed", ""]
        width = max((len(e) for e, _ in top), default=4)
        biggest = top[0][1] if top else 1
        for e, n in top:
            bar = "█" * max(1, round(24 * n / biggest))
            lines.append(f"{e:<{width}}  {bar} {n:,}")
        self.preview.text.setPlainText("\n".join(lines))
        self.preview.stack.setCurrentWidget(self.preview.text)
        self.preview.caption.setText("")
        self._set_props([("archive", archive.mnf), ("path", folder.label_path())])
        self._buttons(("queue", "extract", "copy", "pin"))

    def show_file(self, archive, row):
        self.current = ("file", (archive, row))
        self.name.setText(archive.base_name(row) if archive.names.get(row) else f"#{row:06d}")
        self.badge.setText("loading")
        self.preview.show_message("Loading…")
        self._set_props([
            ("path", archive.path(row)),
            ("archive", archive.mnf),
            ("file index", f"{archive.fidx[row]}  ·  row {row}  ·  {archive.dat_name(archive.arch[row])}"),
            ("size", f"{tables.exact_size(archive.size[row])}  ·  packed {tables.human_size(archive.zsize[row])}"),
        ])
        visible = ["queue", "extract", "copy"]
        if archive.ext(row) == "lang":
            visible.append("lang")
        self._buttons(visible)

    def file_ready(self, archive, row, paths, source):
        if self.current != ("file", (archive, row)):
            return
        self.preview.show_file(paths)
        self.badge.setText({"extracted": "from your extracted files", "cache": "from the preview cache"}.get(source, source or ""))
        self.buttons["open"].setVisible(self.preview.path is not None)
        self.buttons["save"].setVisible(self.preview.image is not None)

    def file_failed(self, archive, row, message):
        if self.current == ("file", (archive, row)):
            self.preview.show_message(message)
            self.badge.setText("")

    def copy_path(self):
        if not self.current:
            return
        kind, (archive, value) = self.current
        QApplication.clipboard().setText(value.label_path() if kind == "folder" else archive.path(value))

    def open_external(self):
        if self.preview.path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.preview.path))

    def save_image(self):
        if self.preview.image is None or not self.current:
            return
        _, (archive, row) = self.current
        base = archive.base_name(row).rsplit(".", 1)[0] if archive.names.get(row) else f"{row:06d}"
        path, _ = QFileDialog.getSaveFileName(self, "Save image", base + ".png", "PNG image (*.png)")
        if path:
            self.preview.image.save(path, "PNG")


class ExtractQueue(QFrame):
    def __init__(self, tool_fn, parent=None):
        super().__init__(parent)
        self.setObjectName("queue")
        self.tool_fn = tool_fn
        self.items = []
        self.jobs = []
        self.running = False
        self.bridge = Bridge()
        self.bridge.progress.connect(self._progress)
        self.bridge.log.connect(lambda line: self.log.appendPlainText(line))
        self.bridge.finished.connect(self._finished)
        st = settings()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        bar = QFrame()
        bar.setObjectName("queueBar")
        self.head = bar
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(14, 6, 14, 6)
        self.toggle = QToolButton()
        self.toggle.setObjectName("queueToggle")
        self.toggle.setCheckable(True)
        self.toggle.setText("Queue")
        self.toggle.setToolTip("Show or hide the queue (Ctrl+E)")
        self.summary = QLabel("Empty. Add folders, files or search results to extract them together.")
        self.summary.setObjectName("queueSummary")
        self.quick = QPushButton("Extract")
        self.quick.setProperty("accent", True)
        self.quick.setEnabled(False)
        bl.addWidget(self.toggle)
        bl.addWidget(self.summary, 1)
        bl.addWidget(self.quick)
        outer.addWidget(bar)

        self.body = QFrame()
        self.body.setObjectName("queueBody")
        grid = QHBoxLayout(self.body)
        grid.setContentsMargins(14, 8, 14, 12)
        grid.setSpacing(14)

        col1 = QVBoxLayout()
        col1.setSpacing(6)
        col1.addWidget(section("IN THE QUEUE"))
        self.list = QListWidget()
        self.list.setObjectName("queueList")
        col1.addWidget(self.list, 1)
        row = QHBoxLayout()
        remove = QPushButton("Remove")
        clear = QPushButton("Clear")
        remove.clicked.connect(self.remove_selected)
        clear.clicked.connect(self.clear)
        row.addWidget(remove)
        row.addWidget(clear)
        row.addStretch(1)
        col1.addLayout(row)

        col2 = QVBoxLayout()
        col2.setSpacing(6)
        col2.addWidget(section("ONLY THESE KINDS"))
        self.exts = QListWidget()
        self.exts.setObjectName("extList")
        self.exts.setFlow(QListWidget.LeftToRight)
        self.exts.setWrapping(True)
        self.exts.setResizeMode(QListWidget.Adjust)
        self.exts.setSpacing(4)
        col2.addWidget(self.exts, 1)
        self.name_filter = QLineEdit()
        self.name_filter.setPlaceholderText("and names containing… (optional)")
        self.name_filter.setClearButtonEnabled(True)
        col2.addWidget(self.name_filter)

        col3 = QVBoxLayout()
        col3.setSpacing(6)
        col3.addWidget(section("WRITE TO"))
        self.dest = PathRow(st.value("extract/dest", os.path.join(config.HOME, "ESO-Extracted")), "Extract to")
        col3.addWidget(self.dest)
        self.preserve = QCheckBox("Keep the archive's folder paths")
        self.preserve.setChecked(st.value("extract/preserve", True, type=bool))
        self.png = QCheckBox("Also write PNGs for DDS textures")
        self.png.setChecked(st.value("extract/png", False, type=bool))
        self.keep_dds = QCheckBox("Keep the DDS files")
        self.keep_dds.setChecked(st.value("extract/keep_dds", True, type=bool))
        self.lang = QCheckBox("Also write CSVs for LANG files")
        self.lang.setChecked(st.value("extract/lang", False, type=bool))
        self.numbered = QCheckBox("Keep numbered copies (<archive>/<row>.<ext>)")
        self.numbered.setChecked(st.value("extract/numbered", False, type=bool))
        self.png.toggled.connect(self.keep_dds.setEnabled)
        self.keep_dds.setEnabled(self.png.isChecked())
        opts = QVBoxLayout()
        opts.setSpacing(4)
        opts.setContentsMargins(0, 4, 0, 6)
        for w in (self.preserve, self.png, self.keep_dds, self.lang, self.numbered):
            if w is self.keep_dds:
                indent = QHBoxLayout()
                indent.addSpacing(24)
                indent.addWidget(w, 1)
                opts.addLayout(indent)
            else:
                opts.addWidget(w)
        col3.addLayout(opts)
        self.go = QPushButton("Extract the queue")
        self.go.setProperty("accent", True)
        self.go.setMinimumHeight(34)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.status = QLabel("")
        self.status.setObjectName("queueStatus")
        self.status.setWordWrap(True)
        actions = QHBoxLayout()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.open_btn = QPushButton("Open folder")
        self.log_btn = QToolButton()
        self.log_btn.setText("Log")
        self.log_btn.setCheckable(True)
        actions.addWidget(self.cancel_btn)
        actions.addWidget(self.open_btn)
        actions.addWidget(self.log_btn)
        actions.addStretch(1)
        col3.addWidget(self.go)
        col3.addWidget(self.bar)
        col3.addWidget(self.status)
        col3.addLayout(actions)
        grid.addLayout(col1, 3)
        grid.addLayout(col2, 3)
        grid.addLayout(col3, 4)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(mono_font())
        self.log.setMaximumBlockCount(4000)
        self.log.setMaximumHeight(160)
        self.log.hide()
        outer.addWidget(self.body, 1)
        outer.addWidget(self.log)
        self.body.hide()
        self.toggle.toggled.connect(self.body.setVisible)
        self.log_btn.toggled.connect(self.log.setVisible)
        self.quick.clicked.connect(self.start)
        self.go.clicked.connect(self.start)
        self.cancel_btn.clicked.connect(self.cancel)
        self.open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.dest.path())))
        self.exts.itemChanged.connect(lambda _: self.update_summary())
        self.name_filter.textChanged.connect(lambda _: self.update_summary())

    def add(self, archive, rows, label, base=None, substring=None):
        if not len(rows):
            return
        self.items.append({"archive": archive, "rows": array("L", rows), "label": label, "base": base, "substring": substring})
        size = sum(archive.size[r] for r in rows)
        it = QListWidgetItem(f"{label}   ·   {len(rows):,} files, {tables.human_size(size)}")
        it.setToolTip(f"{archive.label}\n{label}")
        self.list.addItem(it)
        self._rebuild_exts()
        self.toggle.setChecked(True)

    def remove_selected(self):
        for it in self.list.selectedItems():
            i = self.list.row(it)
            self.list.takeItem(i)
            del self.items[i]
        self._rebuild_exts()

    def clear(self):
        self.list.clear()
        self.items = []
        self._rebuild_exts()

    def _rebuild_exts(self):
        was_off = {self.exts.item(i).data(ROLE_DATA) for i in range(self.exts.count())
                   if self.exts.item(i).checkState() != Qt.Checked}
        counts = {}
        for item in self.items:
            a = item["archive"]
            for r in item["rows"]:
                e = a.ext(r) or "unnamed"
                counts[e] = counts.get(e, 0) + 1
        self.exts.blockSignals(True)
        self.exts.clear()
        for e, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            it = QListWidgetItem(f"{e} {n:,}")
            it.setData(ROLE_DATA, e)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked if e in was_off else Qt.Checked)
            self.exts.addItem(it)
        self.exts.blockSignals(False)
        self.update_summary()

    def chosen(self):
        exts = {self.exts.item(i).data(ROLE_DATA) for i in range(self.exts.count())
                if self.exts.item(i).checkState() == Qt.Checked}
        needle = self.name_filter.text().strip().replace("\\", "/").lower()
        out = {}
        for item in self.items:
            a = item["archive"]
            keep = out.setdefault(a, set())
            for r in item["rows"]:
                if (a.ext(r) or "unnamed") not in exts:
                    continue
                if needle and needle not in a.path(r).lower():
                    continue
                keep.add(r)
        return {a: sorted(rows) for a, rows in out.items() if rows}

    def update_summary(self):
        chosen = self.chosen()
        n = sum(len(r) for r in chosen.values())
        size = sum(a.size[r] for a, rows in chosen.items() for r in rows)
        if not self.items:
            self.summary.setText("Empty. Add folders, files or search results to extract them together.")
        else:
            self.summary.setText(f"{len(self.items)} item(s)  ·  {n:,} files  ·  {tables.human_size(size)}")
        self.quick.setEnabled(n > 0 and not self.running)
        self.go.setEnabled(n > 0 and not self.running)

    def _plans(self, chosen):
        plans = []
        for archive, rows in chosen.items():
            items = [i for i in self.items if i["archive"] is archive]
            only = items[0] if len(items) == 1 else None
            if only and only["substring"] and len(rows) == len(only["rows"]) and not self.name_filter.text().strip():
                plans.append((archive, runner.substring_plan(archive, only["substring"], rows)))
            else:
                plans.append((archive, runner.plan(archive, rows)))
        return plans

    def start(self):
        chosen = self.chosen()
        if not chosen or self.running:
            return
        tool = self.tool_fn()
        problem = tool.problem()
        if problem:
            QMessageBox.critical(self, "Extract", problem)
            return
        dest = self.dest.path()
        plans = self._plans(chosen)
        seconds = sum(runner.plan_seconds(p) for _, p in plans)
        total = sum(a.size[r] for a, rows in chosen.items() for r in rows)
        peak = max((r.size for _, p in plans for r in p), default=0) * 2
        os.makedirs(dest, exist_ok=True)
        free = shutil.disk_usage(dest).free
        if free < total + peak:
            QMessageBox.warning(self, "Not enough space", f"This needs about {tables.human_size(total + peak)} while it runs; "
                                f"{dest} has {tables.human_size(free)} free.")
            return
        runs = sum(len(p) for _, p in plans)
        if seconds > 600 and QMessageBox.question(self, "Extract", f"{runs:,} EsoExtractData runs, about {fmt_seconds(seconds)}, "
                                                    f"{tables.human_size(total)} written. Start?") != QMessageBox.Yes:
            return
        st = settings()
        st.setValue("extract/dest", dest)
        for key, box in (("preserve", self.preserve), ("png", self.png), ("keep_dds", self.keep_dds),
                         ("lang", self.lang), ("numbered", self.numbered)):
            st.setValue("extract/" + key, box.isChecked())
        self.running = True
        self.jobs = []
        self.update_summary()
        self.cancel_btn.setEnabled(True)
        self.toggle.setChecked(True)
        self.status.setText(f"{runs:,} runs, about {fmt_seconds(seconds)}")
        self.log.appendPlainText(f"Extracting {sum(len(r) for r in chosen.values()):,} files ({tables.human_size(total)}) to {dest}")
        threading.Thread(target=self._work, args=(tool, plans, dest), daemon=True).start()

    def _work(self, tool, plans, dest):
        b = self.bridge
        ok, missing, written = True, 0, 0
        try:
            for archive, runs in plans:
                bases = [i["base"] for i in self.items if i["archive"] is archive and i["base"] is not None]
                base = bases[0] if len(bases) == 1 and bases[0].kind == "dir" else None
                opts = runner.Options(dest, preserve_parents=self.preserve.isChecked(), base=base.path() if base else "/",
                                      png=self.png.isChecked(), keep_dds=self.keep_dds.isChecked(),
                                      lang_csv=self.lang.isChecked(), keep_numbered=self.numbered.isChecked())
                job = runner.Job(tool, archive, runs, opts, on_progress=b.progress.emit, on_log=b.log.emit)
                self.jobs.append(job)
                b.log.emit(f"== {archive.label}")
                ok = job.execute() and ok
                missing += len(job.missing)
                written += len(job.written)
                if job.cancel.is_set():
                    break
            text = f"Wrote {written:,} files to {dest}."
            if missing:
                text += f" {missing:,} could not be read."
            b.finished.emit(ok, text)
        except Exception as err:
            b.finished.emit(False, f"Stopped: {err}")

    def cancel(self):
        for job in self.jobs:
            job.stop()
        self.cancel_btn.setEnabled(False)
        self.status.setText("Cancelling…")

    def _progress(self, frac, text):
        self.bar.setValue(int(frac * 1000))
        self.status.setText(text)

    def _finished(self, ok, text):
        cancelled = any(j.cancel.is_set() for j in self.jobs)
        self.status.setText(("Cancelled. " if cancelled else "") + text)
        self.log.appendPlainText(text)
        if ok:
            self.bar.setValue(1000)
        self.running = False
        self.cancel_btn.setEnabled(False)
        self.update_summary()


class SetupPage(QFrame):
    recheck = Signal()
    chooseExe = Signal()
    addGame = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("setup")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 30, 40, 30)
        lay.setSpacing(14)
        title = QLabel("Before browsing")
        title.setObjectName("setupTitle")
        intro = QLabel("This app reads the game's archives through UESP's EsoExtractData, a Windows program that runs "
                       "under Wine or Steam's Proton. Nothing here is bundled with the app; set up what is missing below.")
        intro.setWordWrap(True)
        lay.addWidget(title)
        lay.addWidget(intro)
        self.rows = {}
        for key in ("wine", "exe", "game"):
            box = QFrame()
            box.setObjectName("setupCard")
            bl = QVBoxLayout(box)
            head = QLabel()
            head.setObjectName("setupHead")
            body = QLabel()
            body.setWordWrap(True)
            body.setTextInteractionFlags(Qt.TextSelectableByMouse)
            buttons = QHBoxLayout()
            bl.addWidget(head)
            bl.addWidget(body)
            bl.addLayout(buttons)
            lay.addWidget(box)
            self.rows[key] = (head, body, buttons)
        b = self.rows["exe"][2]
        choose = QPushButton("Choose the EsoExtractData folder…")
        choose.clicked.connect(self.chooseExe.emit)
        page = QPushButton("Open the UESP download page")
        page.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(engine.UESP_PAGE)))
        b.addWidget(choose)
        b.addWidget(page)
        b.addStretch(1)
        g = self.rows["game"][2]
        add = QPushButton("Add a game folder…")
        add.clicked.connect(self.addGame.emit)
        g.addWidget(add)
        g.addStretch(1)
        again = QPushButton("Check again")
        again.setProperty("accent", True)
        again.clicked.connect(self.recheck.emit)
        lay.addWidget(again, 0, Qt.AlignLeft)
        lay.addStretch(1)

    def update_state(self, builds, build, exe_dir, installs, searching=False):
        ok, missing = "✓ ", "✗ "
        head, body, _ = self.rows["wine"]
        if build is not None:
            head.setText(ok + "Wine or Proton")
            others = ", ".join(b.label for b in builds if b is not build)
            body.setText(f"Using {build.label} ({build.wine})." + (f" Also found: {others}." if others else ""))
        else:
            head.setText(missing + "Wine or Proton")
            body.setText("Neither Wine nor a Proton build was found. Install one of them, then press Check again:\n"
                         "  Arch / CachyOS / Manjaro:  sudo pacman -S wine\n"
                         "  Debian / Ubuntu / Mint:  sudo apt install wine\n"
                         "  Fedora:  sudo dnf install wine\n"
                         "  openSUSE:  sudo zypper install wine\n"
                         "Or install any Proton version from Steam (Library > Tools); the app finds it on its own.")
        head, body, _ = self.rows["exe"]
        issue = engine.exe_problem(exe_dir)
        if issue is None:
            head.setText(ok + "EsoExtractData")
            body.setText(f"Found in {exe_dir}.")
        elif searching:
            head.setText("… EsoExtractData")
            body.setText("Looking through your home folder and your other drives for EsoExtractData.exe. "
                         "This takes up to ten seconds.")
        else:
            head.setText(missing + "EsoExtractData")
            body.setText("Download EsoExtractData from UESP, unpack the whole zip into a folder (EsoExtractData.exe "
                         "needs the DLLs next to it, oo2core_8_win64.dll among them), and choose that folder here."
                         + (f"\nNow set to: {exe_dir}" if exe_dir else ""))
        head, body, _ = self.rows["game"]
        if installs:
            head.setText(ok + "The Elder Scrolls Online")
            body.setText("\n".join(i.path for i in installs))
        else:
            head.setText(missing + "The Elder Scrolls Online")
            body.setText("No game folder found in your Steam libraries, Wine/Proton prefixes, Lutris, Heroic, Bottles "
                         "or mounted drives. Add the folder that holds depot/ and game/.")
