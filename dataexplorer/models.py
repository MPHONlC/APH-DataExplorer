# Copyright © 2026 @APHONlC. All rights reserved.
#
# No copying, modification, distribution, or sale without prior written permission.
# AI/ML ingestion and training are strictly prohibited (TDM opt-out).
#
# See LICENSE.md for full terms and maintenance exceptions.

from PySide6.QtCore import QAbstractItemModel, QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QApplication, QStyle

from . import tables

COLUMNS = ("Name", "Type", "Size", "Packed")
_icons = {}


def icon(kind):
    found = _icons.get(kind)
    if found is None:
        found = _icons[kind] = QApplication.style().standardIcon(kind)
    return found


class FolderOutlineModel(QAbstractItemModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.archive = None
        self._registry = []

    def set_archive(self, archive):
        self.beginResetModel()
        self.archive = archive
        self._registry = []
        if archive is not None and archive.loaded:
            for f in self._walk(archive.root):
                f.uid = None
        self.endResetModel()

    def _walk(self, folder):
        stack = [folder]
        while stack:
            f = stack.pop()
            yield f
            stack.extend(f.subs.values())

    def _id(self, folder):
        if folder.uid is None:
            folder.uid = len(self._registry)
            self._registry.append(folder)
        return folder.uid

    def folder(self, index):
        if not index.isValid():
            return self.archive.root if self.archive and self.archive.loaded else None
        return self._registry[index.internalId()]

    def index(self, row, column, parent=QModelIndex()):
        base = self.folder(parent)
        if base is None or column != 0:
            return QModelIndex()
        subs = base.sorted_subs()
        if row < 0 or row >= len(subs):
            return QModelIndex()
        return self.createIndex(row, 0, self._id(subs[row]))

    def parent(self, index):
        if not index.isValid():
            return QModelIndex()
        f = self._registry[index.internalId()]
        p = f.parent
        if p is None or p.parent is None:
            return QModelIndex()
        p.parent.sorted_subs()
        return self.createIndex(p.pos, 0, self._id(p))

    def rowCount(self, parent=QModelIndex()):
        base = self.folder(parent)
        return len(base.sorted_subs()) if base is not None else 0

    def columnCount(self, parent=QModelIndex()):
        return 1

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        f = self._registry[index.internalId()]
        if role == Qt.DisplayRole:
            return "unmapped" if f.kind == "unmapped" else f.name
        if role == Qt.DecorationRole:
            return icon(QStyle.SP_DirIcon)
        if role == Qt.ToolTipRole:
            return f.label_path()
        return None

    def index_of(self, folder):
        if folder is None or folder.parent is None:
            return QModelIndex()
        folder.parent.sorted_subs()
        return self.createIndex(folder.pos, 0, self._id(folder))


class ListingModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.archive = None
        self.entries = []
        self.search_mode = False
        self._sort = (0, Qt.AscendingOrder)

    def show_folder(self, archive, folder):
        self.beginResetModel()
        self.archive, self.search_mode = archive, False
        self.entries = [("folder", f) for f in folder.sorted_subs()] + [("file", r) for r in folder.files]
        self._apply_sort()
        self.endResetModel()

    def show_hits(self, segments):
        self.beginResetModel()
        self.search_mode = True
        self.archive = segments[0][0] if segments else self.archive
        self.entries = [("hit", (a, r)) for a, rows in segments for r in rows]
        self._apply_sort()
        self.endResetModel()

    def clear(self):
        self.beginResetModel()
        self.entries = []
        self.endResetModel()

    def entry(self, row):
        return self.entries[row] if 0 <= row < len(self.entries) else (None, None)

    def file_items(self):
        out = []
        for kind, value in self.entries:
            if kind == "file":
                out.append((self.archive, value))
            elif kind == "hit":
                out.append(value)
        return out

    def item(self, row):
        kind, value = self.entry(row)
        if kind == "file":
            return "file", (self.archive, value)
        return kind, value

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.entries)

    def columnCount(self, parent=QModelIndex()):
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section]
        if orientation == Qt.Horizontal and role == Qt.TextAlignmentRole and section >= 2:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    def _values(self, kind, value):
        a = self.archive
        if kind == "folder":
            files, _, size, zsize = a.stats(value)
            name = "unmapped" if value.kind == "unmapped" else value.name
            return name, f"folder · {files:,} files", size, zsize
        if kind == "hit":
            a, value = value
            return a.path(value), (a.ext(value) or "unnamed") + " · " + a.dat_prefix, a.size[value], a.zsize[value]
        name = a.base_name(value)
        ext = a.ext(value) or "unnamed"
        return name, ext, a.size[value], a.zsize[value]

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        kind, value = self.entries[index.row()]
        col = index.column()
        if role == Qt.DisplayRole:
            return self._cell(kind, value, col)
        if role == Qt.DecorationRole and col == 0:
            return icon(QStyle.SP_DirIcon if kind == "folder" else QStyle.SP_FileIcon)
        if role == Qt.TextAlignmentRole and col >= 2:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.ToolTipRole:
            if kind == "folder":
                return value.label_path()
            if kind == "hit":
                return value[0].path(value[1]) + "\n" + value[0].label
            return self.archive.path(value)
        if role == Qt.ForegroundRole and col == 1:
            return QColor(128, 128, 128)
        if role == Qt.FontRole and kind == "folder" and col == 0:
            f = QFont()
            f.setBold(True)
            return f
        return None

    def _cell(self, kind, value, col):
        a = self.archive
        if kind == "hit":
            a, value = value
            kind = "file"
        if kind == "folder":
            if col == 0:
                return "unmapped" if value.kind == "unmapped" else value.name
            files, _, size, zsize = a.stats(value)
            return (None, f"folder · {files:,} files", tables.human_size(size), tables.human_size(zsize))[col]
        if col == 0:
            return a.path(value) if self.search_mode else a.base_name(value)
        if col == 1:
            ext = a.ext(value) or "unnamed"
            return ext + (" · " + a.dat_prefix if self.search_mode else "")
        return tables.human_size(a.size[value] if col == 2 else a.zsize[value])

    def sort(self, column, order=Qt.AscendingOrder):
        self._sort = (column, order)
        self.beginResetModel()
        self._apply_sort()
        self.endResetModel()

    def _apply_sort(self):
        if self.archive is None:
            return
        column, order = self._sort
        reverse = order == Qt.DescendingOrder

        def key(entry):
            name, typ, size, zsize = self._values(*entry)
            return (name.lower(), typ, size, zsize)[column]

        folders = [e for e in self.entries if e[0] == "folder"]
        files = [e for e in self.entries if e[0] != "folder"]
        if column != 0 or reverse or self.search_mode:
            folders.sort(key=key, reverse=reverse)
            files.sort(key=key, reverse=reverse)
        self.entries = folders + files
