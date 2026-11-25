#!/usr/bin/env python3
"""Universal Base64 Encoder / Decoder — Linux (PyQt5) version.

All controls and layout live in mainwindow.ui (edit it in Qt Designer).
This file holds only the logic, like MainForm.vb in the Windows version.
"""

import base64
import os
import shutil
import sys
import tempfile
import uuid

from PyQt5 import uic
from PyQt5.QtCore import QEvent, QObject, Qt, QTimer, QUrl
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer
from PyQt5.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox

import mimehelper

APP_DIR = os.path.dirname(os.path.realpath(__file__))
UI_PATH = os.path.join(APP_DIR, "mainwindow.ui")
APP_ID = "b64converter"

# MIME values for cboType, in the same order as its items in mainwindow.ui.
# If you add or reorder items in Qt Designer, keep this list in sync.
TYPE_MIMES = [
    "auto",
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml", "image/bmp", "image/x-icon",
    "audio/mpeg", "audio/wav", "audio/ogg", "audio/flac", "audio/mp4",
    "video/mp4", "video/webm",
    "application/pdf", "application/zip", "application/octet-stream",
]

# Text boxes get sluggish with one multi-megabyte line, so very long output is
# shortened on screen only. Copy and Save always use the full text.
DISPLAY_LIMIT = 1_000_000


def fmt_time(ms: int) -> str:
    s = max(0, ms // 1000)
    return f"{s // 3600}:{s // 60 % 60:02}:{s % 60:02}" if s >= 3600 else f"{s // 60}:{s % 60:02}"


class Preview(QObject):
    """Drives one preview area (image / audio / video / message pages) from mainwindow.ui."""

    PAGE_IMAGE, PAGE_MEDIA, PAGE_MESSAGE = 0, 1, 2

    def __init__(self, win, prefix, temp_dir):
        super().__init__(win)
        g = lambda name: getattr(win, prefix + name)
        self.stack, self.image, self.video = g("Preview"), g("Image"), g("Video")
        self.audio_label, self.play_btn = g("AudioLabel"), g("Play")
        self.seek, self.time_label, self.message = g("Seek"), g("Time"), g("Message")
        self.default_message = self.message.text()
        self.folder = os.path.join(temp_dir, prefix)
        os.makedirs(self.folder, exist_ok=True)
        self.pixmap = None
        self.dragging = False

        self.player = QMediaPlayer(self, QMediaPlayer.VideoSurface)
        self.player.setVideoOutput(self.video)
        self.player.stateChanged.connect(self._state_changed)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.positionChanged.connect(self._position_changed)
        self.player.error.connect(self._media_error)
        self.play_btn.clicked.connect(self._toggle_play)
        self.seek.sliderPressed.connect(lambda: setattr(self, "dragging", True))
        self.seek.sliderReleased.connect(self._seek_released)
        self.image.installEventFilter(self)

    # ---- public ----
    def show(self, data: bytes, ext: str, mime: str):
        self.clear()
        if mime.startswith("image/"):
            pm = QPixmap()
            if pm.loadFromData(data):
                self.pixmap = pm
                self.stack.setCurrentIndex(self.PAGE_IMAGE)
                self._rescale()
            else:
                self._show_message("Preview failed — data may be corrupt or the type is wrong.")
        elif mime.startswith(("audio/", "video/")):
            path = os.path.join(self.folder, f"media-{uuid.uuid4().hex}.{ext}")
            with open(path, "wb") as f:
                f.write(data)
            is_video = mime.startswith("video/")
            self.video.setVisible(is_video)
            self.audio_label.setVisible(not is_video)
            self.seek.setRange(0, 0)
            self.time_label.setText("0:00 / 0:00")
            self.stack.setCurrentIndex(self.PAGE_MEDIA)
            self.player.setMedia(QMediaContent(QUrl.fromLocalFile(path)))
            if is_video:
                self.player.play()      # renders the first frames, like the browser preview
                QTimer.singleShot(150, self.player.pause)
        else:
            self._show_message("No direct preview for this file type.")

    def clear(self):
        self.player.stop()
        self.player.setMedia(QMediaContent())
        self.pixmap = None
        self.image.clear()
        self._show_message(self.default_message)
        for name in os.listdir(self.folder):
            try:
                os.remove(os.path.join(self.folder, name))
            except OSError:
                pass

    # ---- internals ----
    def _show_message(self, text):
        self.message.setText(text)
        self.stack.setCurrentIndex(self.PAGE_MESSAGE)

    def _rescale(self):
        if self.pixmap is None:
            return
        size = self.image.size()
        pm = self.pixmap
        if pm.width() > size.width() or pm.height() > size.height():
            pm = pm.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image.setPixmap(pm)

    def eventFilter(self, obj, event):
        if obj is self.image and event.type() == QEvent.Resize:
            self._rescale()
        return False

    def _toggle_play(self):
        if self.player.state() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _state_changed(self, state):
        self.play_btn.setText("⏸ Pause" if state == QMediaPlayer.PlayingState else "▶ Play")

    def _duration_changed(self, duration):
        self.seek.setRange(0, duration)
        self._update_time()

    def _position_changed(self, pos):
        if not self.dragging:
            self.seek.setValue(pos)
        self._update_time()

    def _seek_released(self):
        self.dragging = False
        self.player.setPosition(self.seek.value())

    def _update_time(self):
        self.time_label.setText(f"{fmt_time(self.player.position())} / {fmt_time(self.player.duration())}")

    def _media_error(self, _err):
        self._show_message("Preview failed — data may be corrupt or the type is wrong.\n"
                           f"({self.player.errorString() or 'no playback plugin for this format'})")


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        uic.loadUi(UI_PATH, self)
        self.setAcceptDrops(True)
        self.setWindowIcon(app_icon())

        self.temp_dir = tempfile.mkdtemp(prefix="b64converter-")
        self.enc_preview = Preview(self, "enc", self.temp_dir)
        self.dec_preview = Preview(self, "dec", self.temp_dir)

        # Encoder state
        self.enc_bytes = None
        self.enc_name = self.enc_mime = self.enc_raw = self.enc_full = ""
        self.enc_output = ""

        # Decoder state
        self.dec_bytes = None
        self.dec_file_name = self.dec_ext = ""

        self.lblDecError.hide()
        self.cboType.setCurrentIndex(0)

        # Encoder events
        self.dropZone.clicked.connect(self.browse_encode_file)
        for rb in (self.rbFull, self.rbRaw, self.rbHtml, self.rbCss):
            rb.toggled.connect(lambda checked: checked and self.update_encode_output())
        self.btnCopy.clicked.connect(self.copy_output)
        self.btnSaveTxt.clicked.connect(self.save_output_txt)
        self.btnEncClear.clicked.connect(self.clear_encode)

        # Decoder events
        self.btnDecode.clicked.connect(self.do_decode)
        self.btnPaste.clicked.connect(self.paste_decode)
        self.btnDecClear.clicked.connect(self.clear_decode)
        self.btnDownload.clicked.connect(self.save_decoded)

    # =================================================================
    # Drag and drop (whole window; behavior depends on the active tab)
    # =================================================================
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(u.isLocalFile() for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if not paths:
            return
        if self.tabMain.currentWidget() is self.tabEncode:
            self.load_encode_file(paths[0])
        else:
            try:
                with open(paths[0], "r", encoding="utf-8", errors="replace") as f:
                    self.txtDecInput.setPlainText(f.read())
                self.do_decode()
            except OSError as ex:
                self.show_dec_error(f"Couldn't read the file: {ex}")

    # =================================================================
    # Encoder
    # =================================================================
    def browse_encode_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select a file to encode", os.path.expanduser("~"),
                                              "All files (*)")
        if path:
            self.load_encode_file(path)

    def load_encode_file(self, path):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as ex:
            QMessageBox.critical(self, "Error", f"Couldn't read the file:\n{ex}")
            return

        self.enc_bytes = data
        self.enc_name = os.path.basename(path)
        file_ext = os.path.splitext(path)[1].lstrip(".")
        self.enc_mime = (mimehelper.mime_for_extension(file_ext) or mimehelper.sniff(data)
                         or "application/octet-stream")
        self.enc_raw = base64.b64encode(data).decode("ascii")
        self.enc_full = f"data:{self.enc_mime};base64,{self.enc_raw}"

        self.lblEncName.setText(self.enc_name)
        self.lblEncType.setText(self.enc_mime)
        self.lblEncSize.setText(mimehelper.format_bytes(len(data)))
        self.lblEncB64Size.setText(mimehelper.format_bytes(len(self.enc_full)))

        if self.rbFull.isChecked():
            self.update_encode_output()
        else:
            self.rbFull.setChecked(True)      # triggers update_encode_output
        for b in (self.btnCopy, self.btnSaveTxt, self.btnEncClear):
            b.setEnabled(True)

        self.enc_preview.show(data, file_ext or mimehelper.extension_for(self.enc_mime), self.enc_mime)

    def update_encode_output(self):
        if self.enc_bytes is None:
            return
        full, name, mime = self.enc_full, self.enc_name, self.enc_mime
        if self.rbFull.isChecked():
            out = full
        elif self.rbRaw.isChecked():
            out = self.enc_raw
        elif self.rbHtml.isChecked():
            if mime.startswith("image/"):
                out = f'<img src="{full}" alt="{name}">'
            elif mime.startswith("audio/"):
                out = f'<audio controls src="{full}"></audio>'
            elif mime.startswith("video/"):
                out = f'<video controls src="{full}"></video>'
            else:
                out = f'<a href="{full}" download="{name}">Download {name}</a>'
        else:
            out = f"background-image: url('{full}');"

        self.enc_output = out
        if len(out) > DISPLAY_LIMIT:
            self.txtOutput.setPlainText(
                out[:DISPLAY_LIMIT] + f"\n\n… [shortened on screen — {len(out):,} characters in total. "
                                      "Copy and Save use the full text.]")
        else:
            self.txtOutput.setPlainText(out)

    def copy_output(self):
        if self.enc_output:
            QApplication.clipboard().setText(self.enc_output)
            self.flash_status(self.btnCopy, "✔ Copied!")

    def save_output_txt(self):
        if not self.enc_output:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Base64 as text", os.path.join(os.path.expanduser("~"), f"{self.enc_name}_base64.txt"),
            "Text file (*.txt);;All files (*)")
        if path:
            try:
                with open(path, "w", encoding="ascii") as f:
                    f.write(self.enc_output)
                self.flash_status(self.btnSaveTxt, "✔ Saved!")
            except OSError as ex:
                QMessageBox.critical(self, "Error", f"Couldn't save the file:\n{ex}")

    def clear_encode(self):
        self.enc_bytes = None
        self.enc_name = self.enc_mime = self.enc_raw = self.enc_full = self.enc_output = ""
        self.txtOutput.clear()
        for lbl in (self.lblEncName, self.lblEncType, self.lblEncSize, self.lblEncB64Size):
            lbl.setText("-")
        for b in (self.btnCopy, self.btnSaveTxt, self.btnEncClear):
            b.setEnabled(False)
        self.enc_preview.clear()

    # =================================================================
    # Decoder
    # =================================================================
    def paste_decode(self):
        text = QApplication.clipboard().text()
        if not text:
            self.show_dec_error("The clipboard doesn't contain any text.")
            return
        self.txtDecInput.setPlainText(text)
        self.do_decode()

    def show_dec_error(self, msg):
        self.lblDecError.setText("⚠ " + msg)
        self.lblDecError.show()

    def do_decode(self):
        self.lblDecError.hide()
        raw = self.txtDecInput.toPlainText()
        if not raw.strip():
            self.show_dec_error("Nothing to decode. Paste a Base64 string or data URI first.")
            return

        uri_mime, payload = mimehelper.parse_input(raw)
        clean = mimehelper.clean_base64(payload)
        if clean is None:
            self.show_dec_error("Input is not valid Base64. Check for stray characters or a truncated string.")
            return
        try:
            data = base64.b64decode(clean, validate=True)
        except (ValueError, base64.binascii.Error) as ex:
            self.show_dec_error(f"Decoding failed: {ex}")
            return

        # Type priority: manual selection > data URI header > magic-byte sniff > octet-stream
        idx = self.cboType.currentIndex()
        selected = TYPE_MIMES[idx] if 0 <= idx < len(TYPE_MIMES) else "auto"
        if selected != "auto":
            mime, source = selected, "Manual selection"
        elif uri_mime:
            mime, source = uri_mime, "Data URI header"
        elif mimehelper.sniff(data):
            mime, source = mimehelper.sniff(data), "File signature"
        else:
            mime, source = "application/octet-stream", "Unknown (binary)"

        self.dec_ext = mimehelper.extension_for(mime)
        base_name = self.txtDecName.text().strip() or "decoded"
        for bad in '/\\:*?"<>|\0':
            base_name = base_name.replace(bad, "_")
        self.dec_file_name = f"{base_name}.{self.dec_ext}"
        self.dec_bytes = data

        self.lblDecTypeOut.setText(mime)
        self.lblDecSourceOut.setText(source)
        self.lblDecSizeOut.setText(mimehelper.format_bytes(len(data)))
        self.lblDecFileOut.setText(self.dec_file_name)
        self.btnDownload.setEnabled(True)

        self.dec_preview.show(data, self.dec_ext, mime)

    def save_decoded(self):
        if self.dec_bytes is None:
            return
        ext = self.dec_ext
        path, _ = QFileDialog.getSaveFileName(
            self, "Save decoded file", os.path.join(os.path.expanduser("~"), self.dec_file_name),
            f"{ext.upper()} file (*.{ext});;All files (*)")
        if path:
            try:
                with open(path, "wb") as f:
                    f.write(self.dec_bytes)
                self.flash_status(self.btnDownload, "✔ Saved!")
            except OSError as ex:
                QMessageBox.critical(self, "Error", f"Couldn't save the file:\n{ex}")

    def clear_decode(self):
        self.txtDecInput.clear()
        self.cboType.setCurrentIndex(0)
        self.lblDecError.hide()
        self.dec_bytes = None
        self.dec_file_name = self.dec_ext = ""
        for lbl in (self.lblDecTypeOut, self.lblDecSourceOut, self.lblDecSizeOut, self.lblDecFileOut):
            lbl.setText("-")
        self.btnDownload.setEnabled(False)
        self.dec_preview.clear()

    # =================================================================
    # Helpers / lifecycle
    # =================================================================
    def flash_status(self, btn, msg):
        """Briefly swaps a button's caption as a lightweight 'toast'."""
        if btn.property("flashing"):
            return
        original = btn.text()
        btn.setProperty("flashing", True)
        btn.setText(msg)

        def restore():
            btn.setText(original)
            btn.setProperty("flashing", False)
        QTimer.singleShot(1800, restore)

    def closeEvent(self, e):
        self.enc_preview.player.stop()
        self.dec_preview.player.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        super().closeEvent(e)


def app_icon() -> QIcon:
    local = os.path.join(APP_DIR, "icons", "b64converter-256.png")
    return QIcon.fromTheme(APP_ID, QIcon(local) if os.path.exists(local) else QIcon())


def main():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_ID)        # also the X11 window class (matches StartupWMClass)
    app.setDesktopFileName(APP_ID)        # lets GNOME match the window to its menu entry/icon
    app.setStyle("Fusion")
    app.setWindowIcon(app_icon())
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
