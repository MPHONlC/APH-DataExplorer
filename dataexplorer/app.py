# Copyright © 2026 @APHONlC. All rights reserved.
#
# No copying, modification, distribution, or sale without prior written permission.
# AI/ML ingestion and training are strictly prohibited (TDM opt-out).
#
# See LICENSE.md for full terms and maintenance exceptions.

import os
import shutil
import sys
import threading
import time

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QAction, QActionGroup, QColor, QDesktopServices, QGuiApplication, QIcon, QKeySequence,
                           QPainter, QPainterPath, QPalette, QPen, QPixmap, QShortcut)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFileDialog, QHeaderView, QLabel, QListWidget,
                               QListWidgetItem, QMainWindow, QMenu, QMessageBox, QSplitter, QStackedWidget, QTreeView,
                               QVBoxLayout, QWidget)

from . import __version__, config, dialogs, engine, previews, runner, tables
from .models import FolderOutlineModel, ListingModel
from .ui import ArchiveStrip, Breadcrumb, ExtractQueue, HeaderBar, Inspector, SetupPage

GROUNDS = {
    "dark": {"ground": "#14171b", "panel": "#1a1e23", "raised": "#232830", "hover": "#2d333c", "line": "#343b45",
             "text": "#e6e9ed", "dim": "#9ba3ad", "tile": "#0b0d10"},
    "light": {"ground": "#f3f5f7", "panel": "#ffffff", "raised": "#eceff3", "hover": "#e1e6ec", "line": "#d3d9e0",
              "text": "#1c2024", "dim": "#5a636d", "tile": "#0b0d10"},
}
ACCENTS = {
    "dark": {
        "green": {"accent": "#34d27b", "accent_hover": "#62e5a0", "accent_text": "#03130a", "accent_soft": "#11301f",
                  "select": "#17432b"},
        "blue": {"accent": "#4b9cff", "accent_hover": "#7db8ff", "accent_text": "#020c1a", "accent_soft": "#0f2440",
                 "select": "#173a68"},
    },
    "light": {
        "green": {"accent": "#14804a", "accent_hover": "#0f6a3d", "accent_text": "#ffffff", "accent_soft": "#dcf2e5",
                  "select": "#c3e9d2"},
        "blue": {"accent": "#1f6fd6", "accent_hover": "#185bb0", "accent_text": "#ffffff", "accent_soft": "#dde9fb",
                 "select": "#c8dbf7"},
    },
}
THEME_NAMES = (("dark", "Dark"), ("light", "Light"))
ACCENT_NAMES = (("green", "Green"), ("blue", "Blue"))


def theme_choice():
    st = dialogs.settings()
    ground = st.value("view/theme", "dark")
    accent = st.value("view/accent", "green")
    return (ground if ground in GROUNDS else "dark"), (accent if accent in ("green", "blue") else "green")


class Hub(QObject):
    archiveLoaded = Signal(object)
    archiveFailed = Signal(object, str)
    previewReady = Signal(object, int, list, str)
    previewFailed = Signal(object, int, str)
    status = Signal(str)
    toolsFound = Signal(list, list)


class Loader:
    def __init__(self, hub, make_tool):
        self.hub, self.make_tool = hub, make_tool
        self.queue = []
        self.cv = threading.Condition()
        threading.Thread(target=self._loop, daemon=True).start()

    def request(self, archive, front=False):
        with self.cv:
            if archive.loaded:
                return
            if archive in self.queue:
                if front:
                    self.queue.remove(archive)
                    self.queue.insert(0, archive)
                return
            self.queue.insert(0, archive) if front else self.queue.append(archive)
            self.cv.notify()

    def _loop(self):
        while True:
            with self.cv:
                while not self.queue:
                    self.cv.wait()
                archive = self.queue.pop(0)
            if archive.loaded:
                continue
            self.hub.status.emit(f"Reading the file table of {archive.label}…")
            try:
                archive.load(self.make_tool())
                archive.error = None
                self.hub.archiveLoaded.emit(archive)
            except Exception as err:
                archive.error = str(err)
                self.hub.archiveFailed.emit(archive, str(err))


class Install:
    def __init__(self, path, archives):
        self.path, self.archives = path, archives
        self.label = config.install_label(path)


def draw_icon(size=256, accent="green"):
    color = QColor(ACCENTS["dark"].get(accent, ACCENTS["dark"]["green"])["accent"])
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 256, size / 256)
    tile = QPainterPath()
    tile.addRoundedRect(QRectF(8, 8, 240, 240), 54, 54)
    p.fillPath(tile, QColor("#0b0d10"))
    p.setPen(QPen(QColor("#2b3038"), 3))
    p.drawPath(tile)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#4a515b"))
    for y, width in ((52, 116), (84, 140), (116, 106), (148, 76)):
        p.drawRoundedRect(QRectF(44, y, width, 16), 8, 8)
    glass = QPainterPath()
    glass.addEllipse(QRectF(110, 110, 80, 80))
    p.fillPath(glass, QColor("#0b0d10"))
    p.save()
    p.setClipPath(glass)
    p.setBrush(color)
    for y, width in ((116, 160), (148, 126)):
        p.drawRoundedRect(QRectF(44, y, width, 16), 8, 8)
    p.restore()
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(color, 16))
    p.drawEllipse(QRectF(102, 102, 96, 96))
    pen = QPen(color, 24)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.drawLine(190, 190, 220, 220)
    p.end()
    return pm


def app_icon(accent="green"):
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(draw_icon(size, accent))
    return icon


def apply_theme(app, ground="dark", accent="green"):
    ground = ground if ground in GROUNDS else "dark"
    t = dict(GROUNDS[ground], **ACCENTS[ground].get(accent, ACCENTS[ground]["green"]))
    check = os.path.join(config.cache_dir(), "check-%s.svg" % t["accent_text"].lstrip("#"))
    if not os.path.exists(check):
        with open(check, "w", encoding="utf-8") as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M3.5 8.5l3 3 6-7" fill="none" '
                    f'stroke="{t["accent_text"]}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>')
    if app.style().name().lower() != "fusion":
        app.setStyle("Fusion")
    pal = QPalette()
    for role, key in ((QPalette.Window, "ground"), (QPalette.WindowText, "text"), (QPalette.Base, "panel"),
                      (QPalette.AlternateBase, "raised"), (QPalette.Text, "text"), (QPalette.Button, "raised"),
                      (QPalette.ButtonText, "text"), (QPalette.Highlight, "select"), (QPalette.HighlightedText, "text"),
                      (QPalette.PlaceholderText, "dim"), (QPalette.ToolTipBase, "raised"), (QPalette.ToolTipText, "text"),
                      (QPalette.Link, "accent"), (QPalette.Mid, "line"), (QPalette.Dark, "ground"),
                      (QPalette.Light, "hover"), (QPalette.Midlight, "raised"), (QPalette.Shadow, "ground")):
        pal.setColor(role, QColor(t[key]))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(t["dim"]))
    app.setPalette(pal)
    app.setStyleSheet(f"""
        QToolTip {{ background: {t['raised']}; color: {t['text']}; border: 1px solid {t['line']}; padding: 4px 6px; }}
        QFrame#header {{ background: {t['panel']}; border-bottom: 1px solid {t['line']}; }}
        QLabel#appTitle {{ font-size: 16px; font-weight: 700; color: {t['accent']}; letter-spacing: 1px; }}
        QLineEdit {{ padding: 4px 8px; border-radius: 6px; border: 1px solid {t['line']}; background: {t['ground']}; }}
        QLineEdit:hover {{ border-color: {t['dim']}; }}
        QLineEdit:focus {{ border-color: {t['accent']}; }}
        QLineEdit#bigSearch {{ font-size: 14px; padding: 7px 12px; border-radius: 16px; }}
        QComboBox {{ padding: 4px 8px; border-radius: 6px; border: 1px solid {t['line']}; background: {t['raised']}; }}
        QComboBox:hover {{ border-color: {t['accent']}; background: {t['hover']}; }}
        QComboBox QAbstractItemView {{ background: {t['panel']}; border: 1px solid {t['line']}; selection-background-color: {t['select']}; }}
        QFrame#strip {{ background: {t['ground']}; border-bottom: 1px solid {t['line']}; }}
        QToolButton {{ padding: 4px 10px; border-radius: 6px; border: 1px solid transparent; }}
        QToolButton:hover {{ background: {t['hover']}; border-color: {t['line']}; }}
        QToolButton:pressed {{ background: {t['accent_soft']}; border-color: {t['accent']}; }}
        QToolButton#menuButton {{ border-color: {t['line']}; background: {t['raised']}; font-weight: 600; }}
        QToolButton#menuButton:hover {{ border-color: {t['accent']}; background: {t['hover']}; }}
        QToolButton#menuButton::menu-indicator {{ image: none; width: 0; }}
        QToolButton[chip="true"] {{ padding: 4px 12px; border-radius: 12px; border: 1px solid {t['line']}; background: {t['panel']}; }}
        QToolButton[chip="true"]:hover {{ border-color: {t['accent']}; background: {t['hover']}; }}
        QToolButton[chip="true"]:checked {{ background: {t['accent']}; color: {t['accent_text']}; border-color: {t['accent']}; font-weight: 600; }}
        QToolButton[chip="true"]:checked:hover {{ background: {t['accent_hover']}; border-color: {t['accent_hover']}; }}
        QFrame#breadcrumb {{ background: {t['panel']}; border: 1px solid {t['line']}; border-radius: 6px; }}
        QToolButton#crumb {{ padding: 2px 6px; border-radius: 4px; }}
        QToolButton#crumb:hover {{ background: {t['accent_soft']}; color: {t['accent_hover']}; }}
        QLabel#crumbSep, QLabel#hint, QLabel#propKey, QLabel#queueStatus, QLabel#queueSummary {{ color: {t['dim']}; }}
        QLabel#sectionLabel {{ color: {t['dim']}; font-weight: 600; letter-spacing: 1px; }}
        QLabel#crumbBanner {{ color: {t['accent']}; font-weight: 600; padding: 2px 4px; }}
        QFrame#inspector {{ background: {t['panel']}; border-left: 1px solid {t['line']}; }}
        QLabel#inspectorName {{ font-size: 17px; font-weight: 700; }}
        QLabel#badge {{ color: {t['accent']}; background: {t['accent_soft']}; border: 1px solid {t['accent']}; border-radius: 9px; padding: 1px 8px; font-size: 11px; }}
        QLabel#propValue {{ font-family: monospace; }}
        QLabel#previewMessage {{ color: {t['dim']}; font-size: 13px; }}
        QLabel#previewCaption {{ color: {t['dim']}; }}
        QPushButton {{ padding: 6px 14px; border-radius: 6px; border: 1px solid {t['line']}; background: {t['raised']}; }}
        QPushButton:hover {{ border-color: {t['accent']}; background: {t['hover']}; color: {t['accent_hover']}; }}
        QPushButton:pressed {{ background: {t['accent_soft']}; }}
        QPushButton:focus {{ border-color: {t['accent']}; }}
        QPushButton[accent="true"] {{ background: {t['accent']}; color: {t['accent_text']}; border: 1px solid {t['accent']}; font-weight: 700; }}
        QPushButton[accent="true"]:hover {{ background: {t['accent_hover']}; border-color: {t['accent_hover']}; color: {t['accent_text']}; }}
        QPushButton[accent="true"]:pressed {{ background: {t['accent']}; }}
        QPushButton:disabled, QPushButton[accent="true"]:disabled {{ color: {t['dim']}; background: {t['raised']}; border-color: {t['line']}; }}
        QCheckBox {{ spacing: 8px; padding: 2px 0; }}
        QCheckBox:hover {{ color: {t['accent_hover']}; }}
        QCheckBox::indicator {{ width: 15px; height: 15px; border: 1px solid {t['dim']}; border-radius: 4px; background: {t['ground']}; }}
        QCheckBox::indicator:hover {{ border-color: {t['accent']}; }}
        QCheckBox::indicator:checked {{ background: {t['accent']}; border-color: {t['accent']}; image: url("{check}"); }}
        QCheckBox::indicator:disabled {{ border-color: {t['line']}; background: {t['raised']}; }}
        QMenu {{ background: {t['panel']}; border: 1px solid {t['line']}; padding: 4px; }}
        QMenu::item {{ padding: 6px 22px 6px 14px; border-radius: 4px; }}
        QMenu::item:selected {{ background: {t['accent_soft']}; color: {t['accent_hover']}; }}
        QMenu::separator {{ height: 1px; background: {t['line']}; margin: 4px 8px; }}
        QTreeView::item, QListWidget::item {{ padding: 2px 0; }}
        QTreeView::item:hover, QListWidget::item:hover {{ background: {t['hover']}; }}
        QTreeView::item:selected, QListWidget::item:selected {{ background: {t['select']}; color: {t['text']}; }}
        QFrame#queueBar {{ background: {t['raised']}; border-top: 2px solid {t['accent']}; }}
        QToolButton#queueToggle {{ font-weight: 700; padding: 3px 10px; }}
        QToolButton#queueToggle:checked {{ color: {t['accent']}; }}
        QFrame#queueBody {{ background: {t['panel']}; }}
        QListWidget#extList::item {{ border: 1px solid {t['line']}; border-radius: 10px; padding: 3px 9px; }}
        QListWidget#extList::item:hover {{ border-color: {t['accent']}; }}
        QFrame#setup {{ background: {t['ground']}; }}
        QLabel#setupTitle {{ font-size: 22px; font-weight: 700; color: {t['accent']}; }}
        QFrame#setupCard {{ background: {t['panel']}; border: 1px solid {t['line']}; border-radius: 10px; }}
        QLabel#setupHead {{ font-size: 15px; font-weight: 700; }}
        QTreeView, QListWidget {{ border: none; }}
        QDialog QListWidget, QDialog QPlainTextEdit {{ border: 1px solid {t['line']}; border-radius: 6px; }}
        QHeaderView::section {{ background: {t['raised']}; border: none; border-right: 1px solid {t['line']}; padding: 4px 8px; }}
        QHeaderView::section:hover {{ background: {t['hover']}; }}
        QProgressBar {{ border: none; background: {t['raised']}; border-radius: 3px; height: 6px; }}
        QProgressBar::chunk {{ background: {t['accent']}; border-radius: 3px; }}
        QSplitter::handle {{ background: {t['line']}; }}
        QSplitter::handle:hover {{ background: {t['accent']}; }}
        QScrollBar:vertical {{ background: transparent; width: 11px; margin: 0; }}
        QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 0; }}
        QScrollBar::handle {{ background: {t['line']}; border-radius: 5px; min-height: 28px; min-width: 28px; margin: 2px; }}
        QScrollBar::handle:hover {{ background: {t['dim']}; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
        QSlider::groove:horizontal {{ height: 4px; background: {t['line']}; border-radius: 2px; }}
        QSlider::sub-page:horizontal {{ background: {t['accent']}; border-radius: 2px; }}
        QSlider::handle:horizontal {{ width: 14px; margin: -6px 0; border-radius: 7px; background: {t['text']}; }}
        QSlider::handle:horizontal:hover {{ background: {t['accent_hover']}; }}
    """)
    app.setWindowIcon(app_icon(accent))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(config.APP_NAME)
        self.setWindowIcon(app_icon(theme_choice()[1]))
        threading.Thread(target=lambda: __import__("PIL.Image"), daemon=True).start()
        st = dialogs.settings()
        self.exe_dir = st.value("tool/dir", "") or ""
        self.builds = engine.find_wine_builds()
        self.build = engine.pick_wine(self.builds, st.value("tool/wine", ""))
        self.extracted = st.value("extracted/folders", []) or []
        if isinstance(self.extracted, str):
            self.extracted = [self.extracted]
        self.cache_mb = int(st.value("preview/cache_mb", 2000))
        paths = st.value("installs", []) or []
        if isinstance(paths, str):
            paths = [paths]
        paths = [p for p in paths if config.is_install(p)] or config.detect_installs()
        self.searching = False
        self.hub = Hub()
        self.hub.archiveLoaded.connect(self._archive_loaded)
        self.hub.archiveFailed.connect(lambda a, m: self.statusBar().showMessage(f"{a.label}: {m}"))
        self.hub.previewReady.connect(self._preview_ready)
        self.hub.previewFailed.connect(lambda a, r, m: self.inspector.file_failed(a, r, m))
        self.hub.status.connect(lambda text: text and self.statusBar().showMessage(text, 6000))
        self.hub.toolsFound.connect(self._tools_found)
        self.warm = engine.WarmWine()
        self.loader = Loader(self.hub, self.make_tool)
        self.previews = previews.PreviewService(
            self.make_tool, self.extracted_roots,
            on_ready=lambda a, r, p, s: self.hub.previewReady.emit(a, r, p, s),
            on_failed=lambda a, r, m: self.hub.previewFailed.emit(a, r, m),
            on_status=lambda text: self.hub.status.emit(text),
            limit_bytes=lambda: self.cache_mb * 1024 * 1024)
        self.archive = None
        self.folder = None
        self._build_ui()
        self._build_menu()
        self.set_installs(paths)
        geo = st.value("window/geometry")
        if geo:
            self.restoreGeometry(geo)
        else:
            self.resize(1500, 900)
        self.refresh_setup()
        if engine.exe_problem(self.exe_dir) or not st.value("tool/searched", False, type=bool):
            self.find_tools()

    def make_tool(self):
        return runner.Tool(self.exe_dir, self.build)

    def extracted_roots(self):
        dest = dialogs.settings().value("extract/dest", "")
        return list(self.extracted) + ([dest] if dest else [])

    def _build_ui(self):
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.header = HeaderBar()
        self.header.searchChanged.connect(lambda: self.search_timer.start())
        self.strip = ArchiveStrip()
        self.strip.archiveChosen.connect(self.choose_archive)
        self.strip.installChosen.connect(self.choose_install)
        outer.addWidget(self.header)
        outer.addWidget(self.strip)

        self.stack = QStackedWidget()
        self.setup = SetupPage()
        self.setup.recheck.connect(lambda: self.recheck())
        self.setup.chooseExe.connect(self.choose_exe)
        self.setup.addGame.connect(self.add_game)
        body = QSplitter()
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(8, 8, 4, 8)
        ll.setSpacing(6)
        folders_label = QLabel("FOLDERS")
        folders_label.setObjectName("sectionLabel")
        ll.addWidget(folders_label)
        self.outline_model = FolderOutlineModel(self)
        self.outline = QTreeView()
        self.outline.setHeaderHidden(True)
        self.outline.setUniformRowHeights(True)
        self.outline.setModel(self.outline_model)
        self.outline.clicked.connect(lambda idx: self.open_folder(self.outline_model.folder(idx), from_outline=True))
        ll.addWidget(self.outline, 4)
        pinned_label = QLabel("PINNED")
        pinned_label.setObjectName("sectionLabel")
        ll.addWidget(pinned_label)
        self.pinned = QListWidget()
        self.pinned.itemActivated.connect(self.open_pinned)
        self.pinned.itemClicked.connect(self.open_pinned)
        self.pinned.setContextMenuPolicy(Qt.CustomContextMenu)
        self.pinned.customContextMenuRequested.connect(self._pinned_menu)
        ll.addWidget(self.pinned, 1)

        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(6, 8, 6, 8)
        cl.setSpacing(6)
        self.crumbs = Breadcrumb()
        self.crumbs.folderChosen.connect(self.open_folder)
        self.listing_model = ListingModel(self)
        self.listing = QTreeView()
        self.listing.setRootIsDecorated(False)
        self.listing.setUniformRowHeights(True)
        self.listing.setAlternatingRowColors(True)
        self.listing.setSortingEnabled(True)
        self.listing.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.listing.setModel(self.listing_model)
        header = self.listing.header()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col, width in ((1, 150), (2, 90), (3, 90)):
            header.setSectionResizeMode(col, QHeaderView.Interactive)
            header.resizeSection(col, width)
        self.listing.header().setSortIndicator(0, Qt.AscendingOrder)
        self.listing.doubleClicked.connect(self.activate)
        self.listing.selectionModel().currentChanged.connect(lambda cur, _: self.inspect(cur))
        self.listing.setContextMenuPolicy(Qt.CustomContextMenu)
        self.listing.customContextMenuRequested.connect(self._listing_menu)
        cl.addWidget(self.crumbs)
        cl.addWidget(self.listing, 1)

        self.inspector = Inspector()
        self.inspector.addToQueue.connect(self.add_current_to_queue)
        self.inspector.extractNow.connect(self.extract_now)
        self.inspector.langRequested.connect(lambda a, r: (self.inspector.preview.show_message("Converting to CSV…"),
                                                           self.previews.request(a, r, lang_csv=True)))
        self.inspector.pinFolder.connect(self.pin_folder)
        body.addWidget(left)
        body.addWidget(center)
        body.addWidget(self.inspector)
        body.setStretchFactor(0, 2)
        body.setStretchFactor(1, 5)
        body.setStretchFactor(2, 4)
        body.setSizes([260, 700, 540])
        self.stack.addWidget(self.setup)
        self.stack.addWidget(body)
        self.queue = ExtractQueue(self.make_tool)
        self.vsplit = QSplitter(Qt.Vertical)
        self.vsplit.setChildrenCollapsible(False)
        self.vsplit.addWidget(self.stack)
        self.vsplit.addWidget(self.queue)
        self.vsplit.setStretchFactor(0, 1)
        self.vsplit.setStretchFactor(1, 0)
        self.queue.toggle.toggled.connect(lambda on: QTimer.singleShot(0, lambda: self._fit_queue(on)))
        outer.addWidget(self.vsplit, 1)
        self.setCentralWidget(central)
        QTimer.singleShot(0, lambda: self._fit_queue(self.queue.toggle.isChecked()))

        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(220)
        self.search_timer.timeout.connect(self.run_search)
        QShortcut(QKeySequence.Find, self, activated=lambda: self.header.query.setFocus())
        QShortcut(QKeySequence("Backspace"), self.listing, activated=self.go_up)
        QShortcut(QKeySequence("Ctrl+E"), self, activated=lambda: self.queue.toggle.toggle())
        QShortcut(QKeySequence("Return"), self.listing, activated=lambda: self.activate(self.listing.currentIndex()))
        self.engine_label = QLabel()
        self.statusBar().addPermanentWidget(self.engine_label)
        self._load_pins()

    def _build_menu(self):
        menu = QMenu(self)
        menu.addAction("Queue files by name or extension…", self.fill_by_filter)
        menu.addAction("Map tiles only…", self.extract_maps)
        menu.addAction("Everything, sorted (hours)…", self.extract_everything)
        menu.addSeparator()
        menu.addAction("LANG tools…", lambda: dialogs.LangDialog(self.make_tool(), self).exec())
        menu.addAction("Read the file tables again", self.reload_tables)
        menu.addAction("Open the preview cache", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(previews.cache_root())))
        menu.addSeparator()
        ground, accent = theme_choice()
        for title, names, current, setting in (("Theme", THEME_NAMES, ground, "view/theme"),
                                               ("Accent color", ACCENT_NAMES, accent, "view/accent")):
            sub = menu.addMenu(title)
            group = QActionGroup(self)
            for key, label in names:
                a = QAction(label, self, checkable=True)
                a.setChecked(key == current)
                a.triggered.connect(lambda _=False, k=key, s=setting: self.set_theme(s, k))
                group.addAction(a)
                sub.addAction(a)
        menu.addAction("Settings…", self.open_settings)
        menu.addAction("About", self.about)
        menu.addSeparator()
        menu.addAction("Quit", self.close)
        self.header.menu_button.setMenu(menu)

    def set_theme(self, setting, key):
        dialogs.settings().setValue(setting, key)
        ground, accent = theme_choice()
        apply_theme(QApplication.instance(), ground, accent)
        self.setWindowIcon(app_icon(accent))

    def _fit_queue(self, open_):
        bar = self.queue.head.sizeHint().height() + 2
        total = sum(self.vsplit.sizes())
        if open_:
            self.queue.setMaximumHeight(16777215)
            want = min(max(self.queue.sizeHint().height(), 320), int(total * 0.5))
        else:
            self.queue.setMaximumHeight(bar)
            want = bar
        self.vsplit.setSizes([total - want, want])

    def find_tools(self):
        if self.searching:
            return
        self.searching = True
        self.refresh_setup()
        self.statusBar().showMessage("Looking for EsoExtractData and extracted game files…")
        threading.Thread(target=lambda: self.hub.toolsFound.emit(*map(list, config.find_tools())), daemon=True).start()

    def _tools_found(self, exe_dirs, dumps):
        self.searching = False
        st = dialogs.settings()
        st.setValue("tool/searched", True)
        found = []
        if engine.exe_problem(self.exe_dir):
            best = engine.best_tool_folder(exe_dirs)
            if best and engine.exe_problem(best) is None:
                self.exe_dir = best
                st.setValue("tool/dir", best)
                found.append(f"EsoExtractData in {best}")
        new = [d for d in dumps if d not in self.extracted]
        if new:
            self.extracted += new
            st.setValue("extracted/folders", self.extracted)
            found.append(f"{len(new)} extracted folder(s)")
        self.statusBar().showMessage("Found " + " and ".join(found) if found else "Search finished; nothing new found.", 8000)
        self.recheck(search=False)

    def set_installs(self, paths):
        self.installs = [Install(p, [tables.Archive(p, rel) for rel in config.archives_in(p)]) for p in paths if os.path.isdir(p)]
        self.strip.set_installs(self.installs)
        for inst in self.installs:
            for a in sorted(inst.archives, key=lambda a: a.rel.replace(os.sep, "/") != "game/client/game.mnf"):
                self.loader.request(a)
        if self.installs:
            self.choose_install(0)

    def all_archives(self):
        return [a for inst in self.installs for a in inst.archives]

    def choose_install(self, index):
        if not (0 <= index < len(self.installs)):
            return
        inst = self.installs[index]
        current = next((a for a in inst.archives if a.rel.replace(os.sep, "/") == "depot/eso.mnf"), inst.archives[0] if inst.archives else None)
        self.strip.set_archives(inst.archives, current)
        if current:
            self.choose_archive(current)

    def choose_archive(self, archive):
        self.archive = archive
        self.strip.refresh(archive)
        if not archive.loaded:
            self.loader.request(archive, front=True)
            self.outline_model.set_archive(None)
            self.listing_model.clear()
            self.crumbs.set_path(archive, None, f"Reading the file table of {archive.label}…")
            self.inspector.show_nothing()
            return
        self.outline_model.set_archive(archive)
        self.open_folder(archive.root)

    def _archive_loaded(self, archive):
        self.strip.refresh(self.archive)
        if archive is self.archive:
            self.choose_archive(archive)
        if self.header.query.text().strip():
            self.run_search()
        pending = sum(1 for a in self.all_archives() if not a.loaded and a.error is None)
        self.statusBar().showMessage(f"{archive.label}: {archive.n:,} files" + (f"  ·  {pending} still loading" if pending else ""), 6000)

    def open_folder(self, folder, from_outline=False):
        if folder is None or self.archive is None:
            return
        if self.header.query.text():
            self.header.query.blockSignals(True)
            self.header.query.clear()
            self.header.query.blockSignals(False)
        self.folder = folder
        self.listing_model.show_folder(self.archive, folder)
        self.crumbs.set_path(self.archive, folder)
        self.inspector.show_folder(self.archive, folder)
        if not from_outline:
            idx = self.outline_model.index_of(folder)
            if idx.isValid():
                self.outline.setCurrentIndex(idx)
                self.outline.scrollTo(idx)
        self.previews.prefetch_folder(self.archive, folder)

    def go_up(self):
        if self.header.query.text():
            self.header.query.clear()
            return
        if self.folder is not None and self.folder.parent is not None:
            child = self.folder
            self.open_folder(self.folder.parent)
            for i, (kind, value) in enumerate(self.listing_model.entries):
                if value is child:
                    self.listing.setCurrentIndex(self.listing_model.index(i, 0))
                    break

    def activate(self, index):
        kind, value = self.listing_model.item(index.row())
        if kind == "folder":
            self.open_folder(value)
        elif kind in ("file", "hit"):
            self.inspect(index)

    def inspect(self, index):
        if not index.isValid():
            return
        kind, value = self.listing_model.item(index.row())
        if kind == "folder":
            self.inspector.show_folder(self.archive, value)
            return
        archive, row = value
        self.inspector.show_file(archive, row)
        if self.make_tool().problem() and not self.previews.lookup(archive, row)[0]:
            self.inspector.file_failed(archive, row, self.make_tool().problem())
            return
        self.previews.request(archive, row)
        neighbours = []
        for step in range(1, 7):
            k, v = self.listing_model.item(index.row() + step)
            if k in ("file", "hit") and v[0] is archive:
                neighbours.append(v[1])
        if neighbours:
            self.previews.prefetch_rows(archive, neighbours)

    def _preview_ready(self, archive, row, paths, source):
        self.inspector.file_ready(archive, row, paths, source)

    def run_search(self):
        q = self.header.query.text().strip()
        if not q:
            if self.folder is not None and self.archive is not None:
                self.open_folder(self.folder)
            return
        scope = self.header.scope.currentData()
        archives = [self.archive] if scope == "one" and self.archive else [a for a in self.all_archives() if a.loaded]
        start = time.perf_counter()
        segments = []
        try:
            for a in archives:
                if a is not None and a.loaded:
                    segments.append((a, a.search(q, regex=self.header.regex.isChecked())))
        except Exception as err:
            self.crumbs.set_path(self.archive, None, f"That pattern does not work: {err}")
            return
        ms = (time.perf_counter() - start) * 1000
        self.listing_model.show_hits(segments)
        n = self.listing_model.rowCount()
        where = self.archive.label if scope == "one" and self.archive else "every archive"
        self.crumbs.set_path(self.archive, None, f"{n:,} results for “{q}” in {where}  ·  {ms:.0f} ms  ·  Backspace to go back")

    def selected_items(self):
        out = []
        for idx in self.listing.selectionModel().selectedRows():
            out.append(self.listing_model.item(idx.row()))
        return out

    def add_items_to_queue(self, items):
        for kind, value in items:
            if kind == "folder":
                self.queue.add(self.archive, self.archive.rows_below(value), value.label_path(), base=value)
            elif kind in ("file", "hit"):
                archive, row = value
                self.queue.add(archive, [row], archive.path(row), base=archive.folder_of(row))

    def add_current_to_queue(self, kind, value):
        archive, thing = value
        if kind == "folder":
            self.queue.add(archive, archive.rows_below(thing), thing.label_path() if thing.parent else archive.label, base=thing)
        else:
            self.queue.add(archive, [thing], archive.path(thing), base=archive.folder_of(thing))

    def extract_now(self, kind, value):
        self.queue.clear()
        self.add_current_to_queue(kind, value)
        self.queue.start()

    def _listing_menu(self, pos):
        items = self.selected_items()
        if not items:
            return
        menu = QMenu(self)
        menu.addAction(f"Add {len(items)} to the queue" if len(items) > 1 else "Add to the queue",
                       lambda: self.add_items_to_queue(items))
        if self.listing_model.search_mode:
            menu.addAction("Add every result to the queue", self.add_results_to_queue)
        kind, value = items[0]
        if kind == "folder":
            menu.addAction("Open", lambda: self.open_folder(value))
            menu.addAction("Pin this folder", lambda: self.pin_folder(self.archive, value))
        else:
            archive, row = value
            menu.addAction("Show its folder", lambda: self.reveal(archive, row))
        menu.addAction("Copy path", lambda: QApplication.clipboard().setText(
            value.label_path() if kind == "folder" else value[0].path(value[1])))
        menu.exec(self.listing.viewport().mapToGlobal(pos))

    def add_results_to_queue(self):
        by_archive = {}
        for archive, row in self.listing_model.file_items():
            by_archive.setdefault(archive, []).append(row)
        q = self.header.query.text().strip()
        for archive, rows in by_archive.items():
            self.queue.add(archive, rows, f"results for “{q}”", substring=None)

    def reveal(self, archive, row):
        if archive is not self.archive:
            self.choose_archive(archive)
        folder = archive.folder_of(row)
        self.open_folder(folder)
        for i, (kind, value) in enumerate(self.listing_model.entries):
            if kind == "file" and value == row:
                idx = self.listing_model.index(i, 0)
                self.listing.setCurrentIndex(idx)
                self.listing.scrollTo(idx, QAbstractItemView.PositionAtCenter)
                break

    def _load_pins(self):
        self.pins = dialogs.settings().value("pins", []) or []
        if isinstance(self.pins, str):
            self.pins = [self.pins]
        self.pinned.clear()
        for p in self.pins:
            mnf, _, path = p.partition("::")
            pts = any(part.endswith("PTS") for part in mnf.split(os.sep))
            name = os.path.splitext(os.path.basename(mnf))[0]
            item = QListWidgetItem(f"{name}  {path}" + ("  (PTS)" if pts else ""))
            item.setData(Qt.UserRole, p)
            item.setToolTip(f"{mnf}\n{path}")
            self.pinned.addItem(item)

    def pin_folder(self, archive, folder):
        key = f"{archive.mnf}::{folder.label_path()}"
        if folder.kind == "root":
            self.statusBar().showMessage("The archive itself is already one click away in the chips at the top.", 6000)
            return
        if key in self.pins:
            self.statusBar().showMessage(f"{folder.label_path()} is already pinned.", 6000)
            return
        self.pins.append(key)
        dialogs.settings().setValue("pins", self.pins)
        self._load_pins()

    def open_pinned(self, item):
        mnf, _, path = item.data(Qt.UserRole).partition("::")
        for a in self.all_archives():
            if a.mnf == mnf:
                if a is not self.archive:
                    for i, inst in enumerate(self.installs):
                        if a in inst.archives and self.strip.install.currentIndex() != i:
                            self.strip.install.setCurrentIndex(i)
                    self.choose_archive(a)
                if a.loaded:
                    folder = a.find_folder(path)
                    if folder:
                        self.open_folder(folder)
                return

    def _pinned_menu(self, pos):
        item = self.pinned.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        key = item.data(Qt.UserRole)
        menu.addAction("Unpin", lambda: (self.pins.remove(key), dialogs.settings().setValue("pins", self.pins), self._load_pins()))
        menu.exec(self.pinned.viewport().mapToGlobal(pos))

    def fill_by_filter(self):
        dlg = dialogs.FilterDialog(self.all_archives(), self)
        if dlg.exec() != dialogs.QDialog.Accepted:
            return
        a, rows, native = dlg.result_rows()
        if a is None or not len(rows):
            return
        label = f"names containing {native}" if native else "every named file"
        if dlg.ext.text().strip():
            label += f" ({dlg.ext.text().strip()})"
        self.queue.add(a, rows, label, substring=native if native and not dlg.ext.text().strip() else None)

    def extract_maps(self):
        paths = [i.path for i in self.installs]
        if not paths or self._engine_missing():
            return
        dlg = dialogs.MapsDialog(paths, self.extracted, self)
        if dlg.exec() != dialogs.QDialog.Accepted:
            return
        root = dlg.root.path()
        dialogs.settings().setValue("maps/root", root)
        run = dialogs.CommandDialog("Map tiles", self)
        run.run(self.make_tool(), ["--maps", root], install=dlg.install.currentData(), label=f"Map tiles into {root}/MAPS/tiles")
        run.exec()

    def extract_everything(self):
        paths = [i.path for i in self.installs]
        if not paths or self._engine_missing():
            return
        dlg = dialogs.FullDumpDialog(paths, self.extracted, self)
        if dlg.exec() != dialogs.QDialog.Accepted:
            return
        root = dlg.root.path()
        try:
            start = int(dlg.start.text().strip() or 0)
        except ValueError:
            start = 0
        dialogs.settings().setValue("full/root", root)
        log = dialogs.launch_full_dump(self.make_tool(), dlg.install.currentData(), root, start)
        if root not in self.extracted:
            self.extracted.append(root)
            dialogs.settings().setValue("extracted/folders", self.extracted)
        QMessageBox.information(self, "Everything, sorted", f"Started. It keeps running if you close this app.\nLog: {log}")

    def _engine_missing(self):
        problem = self.make_tool().problem()
        if problem:
            QMessageBox.warning(self, "Engine", problem + ".\n\nOpen Menu > Settings, or see the setup page.")
            return True
        return False

    def choose_exe(self):
        path = QFileDialog.getExistingDirectory(self, "Folder you unpacked EsoExtractData into", self.exe_dir or config.HOME)
        if path:
            self.exe_dir = path
            dialogs.settings().setValue("tool/dir", path)
            self.recheck()

    def add_game(self):
        path = QFileDialog.getExistingDirectory(self, "Game folder (the one with depot/ and game/)")
        if path:
            paths = [i.path for i in self.installs] + [path]
            dialogs.settings().setValue("installs", paths)
            self.set_installs(paths)
            self.recheck()

    def recheck(self, search=True):
        if search and engine.exe_problem(self.exe_dir):
            self.find_tools()
        self.builds = engine.find_wine_builds()
        self.build = engine.pick_wine(self.builds, dialogs.settings().value("tool/wine", ""))
        self.previews.reconfigure()
        self.refresh_setup()

    def refresh_setup(self):
        ready = self.make_tool().problem() is None and bool(self.installs)
        self.setup.update_state(self.builds, self.build, self.exe_dir, self.installs, self.searching)
        self.stack.setCurrentIndex(1 if ready else 0)
        if self.build is not None:
            self.engine_label.setText(f"Engine: EsoExtractData via {self.build.label}")
        else:
            self.engine_label.setText("Engine: Wine or Proton missing")
        if ready:
            self.warm.start(self.build)
        for a in self.all_archives():
            if a.error and ready:
                a.error = None
                self.loader.request(a)

    def open_settings(self):
        dlg = dialogs.SettingsDialog([i.path for i in self.installs], self.exe_dir, self.builds, self.build,
                                     self.extracted, self.cache_mb, self)
        if dlg.exec() != dialogs.QDialog.Accepted:
            return
        st = dialogs.settings()
        st.setValue("installs", dlg.installs())
        st.setValue("tool/dir", dlg.exe.path())
        st.setValue("tool/wine", dlg.wine.currentData() or "")
        st.setValue("extracted/folders", dlg.extracted_folders())
        st.setValue("preview/cache_mb", dlg.cache_mb.value())
        self.exe_dir = dlg.exe.path()
        self.extracted = dlg.extracted_folders()
        self.cache_mb = dlg.cache_mb.value()
        self.set_installs(dlg.installs())
        self.recheck(search=False)

    def reload_tables(self):
        shutil.rmtree(os.path.join(config.cache_dir(), "tables"), ignore_errors=True)
        self.set_installs([i.path for i in self.installs])

    def about(self):
        QMessageBox.about(self, "APH Data Explorer",
                          f"<b>APH Data Explorer</b> {__version__}<p>Browse, search, preview and extract the files in "
                          "The Elder Scrolls Online's game archives on Linux.</p>"
                          "<p>The archives are read by UESP's EsoExtractData (Dave Humphrey), which you download "
                          "separately and which runs under Wine or Proton. Decompression inside it is done by "
                          "RAD Game Tools' Oodle. Built with Qt (PySide6) and Pillow.</p>"
                          "<p>My license covers this app's own code only; see LICENSE.md.</p>")

    def closeEvent(self, event):
        dialogs.settings().setValue("window/geometry", self.saveGeometry())
        self.warm.stop()
        super().closeEvent(event)


def main(argv=None):
    QApplication.setApplicationName(config.APP_NAME)
    QApplication.setOrganizationName("APH")
    QGuiApplication.setDesktopFileName(config.APP_ID)
    argv = list(argv or sys.argv)
    if "--write-icon" in argv:
        app = QGuiApplication(argv)
        target = argv[argv.index("--write-icon") + 1]
        return 0 if draw_icon(256, theme_choice()[1]).save(target, "PNG") else 1
    app = QApplication(argv)
    apply_theme(app, *theme_choice())
    win = MainWindow()
    win.show()
    return app.exec()
