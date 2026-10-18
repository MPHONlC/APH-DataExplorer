# Copyright © 2026 @APHONlC. All rights reserved.
#
# No copying, modification, distribution, or sale without prior written permission.
# AI/ML ingestion and training are strictly prohibited (TDM opt-out).
#
# See LICENSE.md for full terms and maintenance exceptions.

import os

import io

from PySide6.QtCore import QSettings, Qt, QUrl
from PySide6.QtGui import QBrush, QColor, QFontDatabase, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSlider, QStackedWidget, QVBoxLayout, QWidget

from . import config, tables

IMAGE_EXT = {"dds", "png", "jpg", "jpeg", "tga", "bmp", "gif"}
TEXT_EXT = {"lua", "xml", "txt", "lst", "csv", "ini", "json", "fx", "hlsl", "ffx", "fxh", "html", "htm", "cfg",
            "md", "tsv", "srt", "addon", "zosft_txt", "glsl", "vert", "frag", "yaml", "yml", "log"}
AUDIO_EXT = {"wav", "ogg", "mp3"}
MAX_TEXT = 2 * 1024 * 1024


def settings():
    return QSettings(config.SETTINGS_ORG, config.SETTINGS_NAME)


def mono_font():
    f = QFontDatabase.systemFont(QFontDatabase.FixedFont)
    f.setPointSizeF(max(9.0, f.pointSizeF()))
    return f


class Checker(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.image = None
        self.setMinimumSize(200, 200)
        tile = QPixmap(16, 16)
        tile.fill(QColor("#3a3a3a"))
        p = QPainter(tile)
        p.fillRect(0, 0, 8, 8, QColor("#2c2c2c"))
        p.fillRect(8, 8, 8, 8, QColor("#2c2c2c"))
        p.end()
        self.brush = QBrush(tile)

    def set_image(self, image):
        self.image = image
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), self.palette().base())
        if self.image is None or self.image.isNull():
            return
        avail = self.rect().adjusted(16, 16, -16, -16)
        w, h = self.image.width(), self.image.height()
        scale = min(avail.width() / w, avail.height() / h, 4.0)
        tw, th = max(1, int(w * scale)), max(1, int(h * scale))
        x = self.rect().center().x() - tw // 2
        y = self.rect().center().y() - th // 2
        p.fillRect(x, y, tw, th, self.brush)
        p.drawImage(x, y, self.image.scaled(tw, th, Qt.KeepAspectRatio,
                                            Qt.SmoothTransformation if scale <= 2 else Qt.FastTransformation))


def fmt_time(ms):
    s = max(0, int(ms // 1000))
    return f"{s // 60}:{s % 60:02d}"


class AudioPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.player = None
        self.output = None
        self.devices = None
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.addStretch(1)
        self.title = QLabel()
        self.title.setObjectName("audioTitle")
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setWordWrap(True)
        row = QHBoxLayout()
        self.play = QPushButton("Play")
        self.play.setObjectName("playButton")
        self.play.setProperty("accent", True)
        self.play.setMinimumWidth(90)
        self.seek = QSlider(Qt.Horizontal)
        self.time = QLabel("0:00 / 0:00")
        self.time.setObjectName("audioTime")
        row.addWidget(self.play)
        row.addWidget(self.seek, 1)
        row.addWidget(self.time)
        out = QHBoxLayout()
        self.device = QComboBox()
        self.device.setToolTip("Where the sound plays")
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(int(settings().value("audio/volume", 80)))
        self.volume.setMaximumWidth(140)
        self.volume.setToolTip("Volume")
        out.addWidget(QLabel("Output"))
        out.addWidget(self.device, 1)
        out.addSpacing(10)
        out.addWidget(QLabel("Volume"))
        out.addWidget(self.volume)
        self.note = QLabel()
        self.note.setObjectName("previewCaption")
        self.note.setAlignment(Qt.AlignCenter)
        self.note.setWordWrap(True)
        lay.addWidget(self.title)
        lay.addLayout(row)
        lay.addLayout(out)
        lay.addWidget(self.note)
        lay.addStretch(1)
        self.play.clicked.connect(self.toggle)
        self.seek.sliderMoved.connect(lambda v: self.player and self.player.setPosition(v))
        self.volume.valueChanged.connect(self._volume)
        self.device.activated.connect(lambda _: self._pick_device(save=True))

    def _ensure(self):
        if self.player is not None:
            return True
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer
        except ImportError:
            self.note.setText("Qt Multimedia is not installed, so sounds open in your default player instead.")
            return False
        self.player = QMediaPlayer(self)
        self.output = QAudioOutput(self)
        self.player.setAudioOutput(self.output)
        self.devices = QMediaDevices(self)
        self.devices.audioOutputsChanged.connect(self._fill_devices)
        self._fill_devices()
        self._volume(self.volume.value(), save=False)
        self.player.durationChanged.connect(lambda d: (self.seek.setRange(0, d), self._time()))
        self.player.positionChanged.connect(lambda p: (self.seek.blockSignals(True), self.seek.setValue(p), self.seek.blockSignals(False), self._time()))
        self.player.playbackStateChanged.connect(lambda st: self.play.setText("Pause" if st == QMediaPlayer.PlayingState else "Play"))
        self.player.errorOccurred.connect(lambda *_: self.note.setText("This sound could not be played: " + self.player.errorString()))
        return True

    def _fill_devices(self):
        from PySide6.QtMultimedia import QMediaDevices
        wanted = settings().value("audio/device", "")
        default = QMediaDevices.defaultAudioOutput()
        self.device.blockSignals(True)
        self.device.clear()
        self.device.addItem(f"System default ({default.description()})", "")
        for dev in QMediaDevices.audioOutputs():
            self.device.addItem(dev.description(), bytes(dev.id()).decode("utf-8", "replace"))
        self.device.setCurrentIndex(max(0, self.device.findData(wanted)))
        self.device.blockSignals(False)
        self._pick_device()

    def _pick_device(self, save=False):
        from PySide6.QtMultimedia import QMediaDevices
        key = self.device.currentData() or ""
        if save:
            settings().setValue("audio/device", key)
        chosen = QMediaDevices.defaultAudioOutput()
        for dev in QMediaDevices.audioOutputs():
            if key and bytes(dev.id()).decode("utf-8", "replace") == key:
                chosen = dev
        if self.output is not None and self.output.device() != chosen:
            self.output.setDevice(chosen)

    def _volume(self, value, save=True):
        if save:
            settings().setValue("audio/volume", value)
        if self.output is not None:
            from PySide6.QtMultimedia import QAudio
            self.output.setVolume(QAudio.convertVolume(value / 100, QAudio.LogarithmicVolumeScale, QAudio.LinearVolumeScale))

    def _time(self):
        if self.player:
            self.time.setText(f"{fmt_time(self.player.position())} / {fmt_time(self.player.duration())}")

    def load(self, path):
        self.title.setText(os.path.basename(path))
        self.note.setText("")
        self.seek.setValue(0)
        if self._ensure():
            self.player.stop()
            self._pick_device()
            self.player.setSource(QUrl.fromLocalFile(path))

    def toggle(self):
        if not self.player:
            return
        from PySide6.QtMultimedia import QMediaPlayer
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self._pick_device()
            self.player.play()

    def stop(self):
        if self.player:
            self.player.stop()


def xv4_image(data):
    at = data.find(b"DDS ")
    if not data.startswith(b"xV4") or at < 0:
        return None
    from PIL import Image
    return Image.open(io.BytesIO(data[at:]))


class Preview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.stack = QStackedWidget()
        self.message = QLabel()
        self.message.setAlignment(Qt.AlignCenter)
        self.message.setWordWrap(True)
        self.message.setObjectName("previewMessage")
        self.canvas = Checker()
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setFont(mono_font())
        self.text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.audio = AudioPanel()
        for w in (self.message, self.canvas, self.text, self.audio):
            self.stack.addWidget(w)
        self.caption = QLabel()
        self.caption.setObjectName("previewCaption")
        lay.addWidget(self.stack, 1)
        lay.addWidget(self.caption)
        self.image = None
        self.path = None

    def show_message(self, text):
        self.audio.stop()
        self.image = None
        self.path = None
        self.message.setText(text)
        self.caption.setText("")
        self.stack.setCurrentWidget(self.message)

    def _show_image(self, im, size, label=None):
        fmt = label or f"{im.format} {im.mode}"
        dims = im.size
        data = im.convert("RGBA").tobytes("raw", "RGBA")
        self.image = QImage(data, dims[0], dims[1], QImage.Format_RGBA8888).copy()
        self.canvas.set_image(self.image)
        self.stack.setCurrentWidget(self.canvas)
        self.caption.setText(f"{dims[0]} × {dims[1]}  ·  {fmt}  ·  {tables.human_size(size)}")

    def show_file(self, paths):
        self.audio.stop()
        self.image = None
        if not paths:
            self.show_message("EsoExtractData did not write this file.")
            return
        audio = [p for p in paths if p.lower().rsplit(".", 1)[-1] in AUDIO_EXT]
        path = paths[0]
        self.path = audio[0] if audio else path
        ext = path.lower().rsplit(".", 1)[-1] if "." in os.path.basename(path) else ""
        size = os.path.getsize(path)
        if ext in IMAGE_EXT:
            try:
                from PIL import Image
                with Image.open(path) as im:
                    self._show_image(im, size)
                return
            except Exception as err:
                self.show_message(f"Could not decode this image: {err}")
                return
        if audio:
            self.path = audio[0]
            self.audio.load(audio[0])
            self.stack.setCurrentWidget(self.audio)
            self.caption.setText(f"{audio[0].rsplit('.', 1)[-1].upper()}  ·  {tables.human_size(os.path.getsize(audio[0]))}")
            return
        with open(path, "rb") as f:
            head = f.read(MAX_TEXT)
        if ext == "xv4" or head.startswith(b"xV4"):
            try:
                with open(path, "rb") as f:
                    im = xv4_image(f.read())
                if im is not None:
                    self._show_image(im, size, f"XV4 texture ({im.mode})")
                    return
            except Exception as err:
                self.show_message(f"Could not decode this texture: {err}")
                return
        if ext == "gr2":
            self.text.setPlainText("Granny 3D model (.gr2).\n\nGranny is a closed format with no open-source reader, so "
                                   "models cannot be shown here. Extract it and open it with a tool that has a Granny "
                                   "importer.\n\nFirst 4 kB as hex:\n\n" + _hexdump(head[:4096]))
            self.stack.setCurrentWidget(self.text)
            self.caption.setText(f"GR2  ·  {tables.human_size(size)}")
            return
        if ext in TEXT_EXT or _looks_like_text(head):
            text = head.decode("utf-8", errors="replace")
            if len(head) == MAX_TEXT:
                text += "\n\n… (first 2 MB only)"
            self.text.setPlainText(text)
            self.stack.setCurrentWidget(self.text)
            self.caption.setText(f"{ext.upper() or 'Text'}  ·  {tables.human_size(size)}")
            return
        self.text.setPlainText(_hexdump(head[:4096]) + ("\n…" if size > 4096 else ""))
        self.stack.setCurrentWidget(self.text)
        self.caption.setText(f"{ext.upper() or 'Binary'}  ·  {tables.human_size(size)}  ·  first 4 kB as hex")


def _looks_like_text(data):
    sample = data[:4096]
    if not sample:
        return True
    if b"\0" in sample:
        return False
    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _hexdump(data):
    lines = []
    for off in range(0, len(data), 16):
        chunk = data[off:off + 16]
        hexs = " ".join(f"{b:02x}" for b in chunk)
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{off:08x}  {hexs:<47}  {text}")
    return "\n".join(lines)
