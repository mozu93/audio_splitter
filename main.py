import os
import sys
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, QTime, QThread, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QSlider,
    QStyle,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from updater import APP_VERSION, check_latest_version, is_newer_version, download_update, launch_updater

SUPPORTED_EXTENSIONS = {".m4a", ".mp3"}


def seconds_to_time(seconds: float) -> QTime:
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return QTime(h, m, s)


def time_to_seconds(t: QTime) -> int:
    return t.hour() * 3600 + t.minute() * 60 + t.second()


def format_hhmmss(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def resource_path(name: str) -> str:
    """PyInstallerでexe化した場合も同梱ファイルを参照できるようにする。"""
    if hasattr(sys, "_MEIPASS"):
        return str(Path(sys._MEIPASS) / name)
    return str(Path(__file__).resolve().parent / name)


def find_ffmpeg() -> str | None:
    """PATH上、またはアプリフォルダ内のffmpegを探す。"""
    found = shutil.which("ffmpeg")
    if found:
        return found

    candidates = [
        Path(resource_path("ffmpeg.exe")),
        Path(resource_path("ffmpeg")),
        Path(__file__).resolve().parent / "bin" / "ffmpeg.exe",
        Path(__file__).resolve().parent / "bin" / "ffmpeg",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


# ── アップデート関連ワーカー ──────────────────────────────────────────


class UpdateCheckWorker(QThread):
    updateFound = Signal(str, str, str)  # tag, download_url, html_url

    def run(self):
        info = check_latest_version()
        if info and is_newer_version(APP_VERSION, info["tag_name"]):
            self.updateFound.emit(info["tag_name"], info["download_url"], info["html_url"])


class DownloadWorker(QThread):
    progress = Signal(int, int)  # received, total
    finished = Signal(str)       # tmp_path
    failed = Signal()

    def __init__(self, url: str):
        super().__init__()
        self.url = url

    def run(self):
        path = download_update(self.url, lambda r, t: self.progress.emit(r, t))
        if path:
            self.finished.emit(path)
        else:
            self.failed.emit()


class UpdateBanner(QFrame):
    """新バージョン検出 → ダウンロード → 自己更新バナー"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("UpdateBanner")
        self.setVisible(False)
        self._download_url = ""
        self._installer_path = ""

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 7, 14, 7)

        self._msg = QLabel("")
        self._msg.setStyleSheet("color: #713F12; font-size: 13px;")
        row.addWidget(self._msg)
        row.addStretch()

        self._dl_btn = QPushButton("ダウンロード")
        self._dl_btn.setFixedHeight(28)
        self._dl_btn.clicked.connect(self._start_download)
        self._dl_btn.setVisible(False)
        row.addWidget(self._dl_btn)

        self._progress_label = QLabel("")
        self._progress_label.setStyleSheet("color: #713F12; font-size: 12px; min-width: 120px;")
        self._progress_label.setVisible(False)
        row.addWidget(self._progress_label)

        self._install_btn = QPushButton("今すぐ更新して再起動")
        self._install_btn.setFixedHeight(28)
        self._install_btn.clicked.connect(self._install)
        self._install_btn.setVisible(False)
        row.addWidget(self._install_btn)

        dismiss = QPushButton("✕")
        dismiss.setFixedSize(26, 26)
        dismiss.setObjectName("DismissBtn")
        dismiss.clicked.connect(lambda: self.setVisible(False))
        row.addWidget(dismiss)

        self._check_worker = UpdateCheckWorker()
        self._check_worker.updateFound.connect(self._on_update_found)
        self._check_worker.start()

    def _on_update_found(self, tag: str, download_url: str, html_url: str):
        self._download_url = download_url
        self._msg.setText(f"新しいバージョン {tag} があります（現在: v{APP_VERSION}）")
        self._dl_btn.setVisible(True)
        self.setVisible(True)

    def _start_download(self):
        self._dl_btn.setVisible(False)
        self._progress_label.setText("準備中...")
        self._progress_label.setVisible(True)
        self._dl_worker = DownloadWorker(self._download_url)
        self._dl_worker.progress.connect(self._on_progress)
        self._dl_worker.finished.connect(self._on_finished)
        self._dl_worker.failed.connect(self._on_failed)
        self._dl_worker.start()

    def _on_progress(self, received: int, total: int):
        mb_r = received / 1048576
        if total > 0:
            self._progress_label.setText(f"{mb_r:.1f} / {total / 1048576:.1f} MB")
        else:
            self._progress_label.setText(f"{mb_r:.1f} MB...")

    def _on_finished(self, path: str):
        self._installer_path = path
        self._progress_label.setVisible(False)
        self._msg.setText("ダウンロード完了！インストールしてアプリを更新できます。")
        self._install_btn.setVisible(True)

    def _on_failed(self):
        self._progress_label.setVisible(False)
        self._msg.setText("ダウンロードに失敗しました。")
        self._dl_btn.setText("再試行")
        self._dl_btn.setVisible(True)

    def _install(self):
        if not self._installer_path:
            return
        if getattr(sys, "frozen", False):
            launch_updater(self._installer_path)
        else:
            subprocess.Popen([self._installer_path])


# ── ドロップエリア ────────────────────────────────────────────────────


class DropArea(QFrame):
    fileDropped = Signal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setObjectName("DropArea")
        self.setMinimumHeight(100)
        self.label = QLabel("ここに m4a / mp3 ファイルをドラッグ＆ドロップ\nまたはクリックして選択")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("font-size: 18px; color: #334155;")
        layout = QVBoxLayout(self)
        layout.addWidget(self.label)

    def mousePressEvent(self, event):
        path, _ = QFileDialog.getOpenFileName(
            self, "音声ファイルを選択", "", "音声ファイル (*.m4a *.mp3)",
        )
        if path:
            self.fileDropped.emit(path)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            file_path = event.mimeData().urls()[0].toLocalFile()
            if Path(file_path).suffix.lower() in SUPPORTED_EXTENSIONS:
                event.acceptProposedAction()
                self.setProperty("drag", True)
                self.style().unpolish(self)
                self.style().polish(self)
                return
        event.ignore()

    def dragLeaveEvent(self, event):
        self.setProperty("drag", False)
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event: QDropEvent):
        self.setProperty("drag", False)
        self.style().unpolish(self)
        self.style().polish(self)
        urls = event.mimeData().urls()
        if urls:
            self.fileDropped.emit(urls[0].toLocalFile())


# ── 切り出しワーカー ──────────────────────────────────────────────────


class CutWorker(QThread):
    finishedOk = Signal(str)
    failed = Signal(str)
    progress = Signal(int)  # 0-100

    def __init__(self, ffmpeg_path: str, input_file: str, output_file: str, start_sec: int, end_sec: int):
        super().__init__()
        self.ffmpeg_path = ffmpeg_path
        self.input_file = input_file
        self.output_file = output_file
        self.start_sec = start_sec
        self.end_sec = end_sec

    def run(self):
        total_sec = self.end_sec - self.start_sec
        try:
            command = [
                self.ffmpeg_path, "-y",
                "-ss", format_hhmmss(self.start_sec),
                "-to", format_hhmmss(self.end_sec),
                "-i", self.input_file,
                "-c", "copy",
                "-progress", "pipe:1",
                "-nostats",
                self.output_file,
            ]
            proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            for line in proc.stdout:
                line = line.strip()
                if line.startswith("out_time=") and total_sec > 0:
                    try:
                        parts = line.split("=", 1)[1].split(":")
                        current_sec = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
                        self.progress.emit(min(99, int(current_sec / total_sec * 100)))
                    except (ValueError, IndexError):
                        pass
            proc.wait()
            stderr_output = proc.stderr.read()
            if proc.returncode == 0 and Path(self.output_file).exists():
                self.progress.emit(100)
                self.finishedOk.emit(self.output_file)
            else:
                self.failed.emit(stderr_output or "ffmpegの実行に失敗しました。")
        except Exception as e:
            self.failed.emit(str(e))


# ── メインウィンドウ ──────────────────────────────────────────────────


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"単純音声ファイル分割ソフト v{APP_VERSION}")
        screen = QApplication.primaryScreen().availableGeometry()
        w = min(760, screen.width() - 40)
        h = min(640, screen.height() - 60)
        self.resize(w, h)
        self.move(screen.x() + (screen.width() - w) // 2, screen.y() + (screen.height() - h) // 2)

        self.ffmpeg_path = find_ffmpeg()
        self.current_file: str | None = None
        self.duration_sec: int | None = None
        self.worker: CutWorker | None = None
        self._seeking = False

        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(0.8)
        self.player.durationChanged.connect(self.on_duration_changed)
        self.player.positionChanged.connect(self._on_position_changed)

        # コンテナ（バナー + スクロール）
        container = QWidget()
        self.setCentralWidget(container)
        container_layout = QVBoxLayout(container)
        container_layout.setSpacing(0)
        container_layout.setContentsMargins(0, 0, 0, 0)

        self.update_banner = UpdateBanner()
        container_layout.addWidget(self.update_banner)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        container_layout.addWidget(scroll)

        root = QWidget()
        scroll.setWidget(root)
        layout = QVBoxLayout(root)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 12, 12, 12)

        title = QLabel("単純音声ファイル分割ソフト")
        title.setStyleSheet("font-size: 26px; font-weight: bold; color: #0f172a;")
        layout.addWidget(title)

        self.ffmpeg_status = QLabel()
        layout.addWidget(self.ffmpeg_status)
        self.update_ffmpeg_status()

        self.drop_area = DropArea()
        self.drop_area.fileDropped.connect(self.load_file)
        layout.addWidget(self.drop_area)

        self.file_label = QLabel("ファイル未選択")
        self.file_label.setStyleSheet("font-size: 14px; color: #475569;")
        layout.addWidget(self.file_label)

        self.load_status_label = QLabel("")
        self.load_status_label.setStyleSheet("font-size: 13px;")
        layout.addWidget(self.load_status_label)

        # 再生コントロール行
        ctrl_row = QHBoxLayout()

        self.rewind_btn = QPushButton("⏪ -10s")
        self.rewind_btn.clicked.connect(self.rewind)
        self.rewind_btn.setEnabled(False)
        ctrl_row.addWidget(self.rewind_btn)

        self.play_btn = QPushButton("▶ 再生")
        self.play_btn.clicked.connect(self.toggle_play)
        self.play_btn.setEnabled(False)
        ctrl_row.addWidget(self.play_btn)

        self.forward_btn = QPushButton("+10s ⏩")
        self.forward_btn.clicked.connect(self.fast_forward)
        self.forward_btn.setEnabled(False)
        ctrl_row.addWidget(self.forward_btn)

        self.stop_btn = QPushButton("⏹ 停止")
        self.stop_btn.clicked.connect(self.stop_play)
        self.stop_btn.setEnabled(False)
        ctrl_row.addWidget(self.stop_btn)

        ctrl_row.addStretch()

        self.time_label = QLabel("--:--:-- / --:--:--")
        self.time_label.setStyleSheet("font-size: 13px; color: #334155;")
        ctrl_row.addWidget(self.time_label)

        layout.addLayout(ctrl_row)

        # シークスライダー
        self.position_slider = QSlider(Qt.Horizontal)
        self.position_slider.setRange(0, 0)
        self.position_slider.sliderPressed.connect(self._on_slider_pressed)
        self.position_slider.sliderReleased.connect(self._on_slider_released)
        self.position_slider.sliderMoved.connect(self._on_slider_moved)
        layout.addWidget(self.position_slider)

        # 音量コントロール行
        vol_row = QHBoxLayout()
        vol_row.addWidget(QLabel("🔊 音量"))

        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.volume_slider.setMaximumWidth(160)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        vol_row.addWidget(self.volume_slider)

        self.volume_label = QLabel("80%")
        self.volume_label.setStyleSheet("color: #334155; min-width: 36px;")
        vol_row.addWidget(self.volume_label)
        vol_row.addStretch()

        layout.addLayout(vol_row)

        form = QFormLayout()
        self.start_edit = QTimeEdit()
        self.start_edit.setDisplayFormat("HH:mm:ss")
        self.start_edit.setTime(QTime(0, 0, 0))
        form.addRow("開始時間", self.start_edit)

        self.end_edit = QTimeEdit()
        self.end_edit.setDisplayFormat("HH:mm:ss")
        self.end_edit.setTime(QTime(0, 10, 0))
        form.addRow("終了時間", self.end_edit)

        self.output_edit = QLineEdit()
        form.addRow("保存先", self.output_edit)

        browse_row = QHBoxLayout()
        self.browse_btn = QPushButton("保存先を選択")
        self.browse_btn.clicked.connect(self.select_output)
        self.browse_btn.setEnabled(False)
        browse_row.addWidget(self.browse_btn)

        self.preview_start_btn = QPushButton("開始位置を確認")
        self.preview_start_btn.clicked.connect(lambda: self.seek_and_play(time_to_seconds(self.start_edit.time())))
        self.preview_start_btn.setEnabled(False)
        browse_row.addWidget(self.preview_start_btn)

        self.preview_end_btn = QPushButton("終了位置を確認")
        self.preview_end_btn.clicked.connect(lambda: self.seek_and_play(time_to_seconds(self.end_edit.time())))
        self.preview_end_btn.setEnabled(False)
        browse_row.addWidget(self.preview_end_btn)
        layout.addLayout(form)
        layout.addLayout(browse_row)

        self.cut_info = QLabel("開始時間・終了時間を指定してください。")
        self.cut_info.setStyleSheet("color: #334155;")
        layout.addWidget(self.cut_info)
        self.start_edit.timeChanged.connect(self.update_cut_info)
        self.end_edit.timeChanged.connect(self.update_cut_info)

        # 進捗バー + パーセント表示
        progress_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)
        progress_row.addWidget(self.progress)

        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet("color: #334155; min-width: 40px;")
        self.progress_label.setVisible(False)
        progress_row.addWidget(self.progress_label)
        layout.addLayout(progress_row)

        self.cut_btn = QPushButton("切り取って保存")
        self.cut_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))
        self.cut_btn.clicked.connect(self.cut_audio)
        self.cut_btn.setEnabled(False)
        self.cut_btn.setMinimumHeight(46)
        layout.addWidget(self.cut_btn)

        note = QLabel("※ 高速・音質劣化なしで切り出すため、ffmpeg の -c copy を使用します。")
        note.setStyleSheet("color: #64748b;")
        layout.addWidget(note)

        self.apply_style()

    def apply_style(self):
        self.setStyleSheet("""
            QMainWindow { background: #f8fafc; }
            QPushButton {
                background: #2563eb;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 9px 14px;
                font-weight: bold;
            }
            QPushButton:disabled { background: #cbd5e1; color: #64748b; }
            QPushButton:hover:!disabled { background: #1d4ed8; }
            QFrame#UpdateBanner {
                background: #FEF9C3;
                border-bottom: 1px solid #FDE047;
            }
            QFrame#UpdateBanner QPushButton {
                padding: 4px 12px;
                border-radius: 6px;
                font-size: 12px;
            }
            QFrame#UpdateBanner QPushButton#DismissBtn {
                background: transparent;
                color: #713F12;
                border: 1px solid #FDE047;
                padding: 2px;
                font-size: 11px;
            }
            QFrame#UpdateBanner QPushButton#DismissBtn:hover {
                background: #FDE047;
            }
            QLineEdit, QTimeEdit {
                background: white;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                padding: 8px;
                font-size: 14px;
            }
            QFrame#DropArea {
                background: white;
                border: 2px dashed #94a3b8;
                border-radius: 16px;
            }
            QFrame#DropArea[drag="true"] {
                background: #eff6ff;
                border: 2px dashed #2563eb;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #e2e8f0;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #2563eb;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #2563eb;
                width: 16px;
                height: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }
            QSlider::handle:horizontal:disabled {
                background: #94a3b8;
            }
            QProgressBar {
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                text-align: center;
                background: #f1f5f9;
            }
            QProgressBar::chunk {
                background: #2563eb;
                border-radius: 6px;
            }
        """)

    def update_ffmpeg_status(self):
        if self.ffmpeg_path:
            self.ffmpeg_status.setText(f"ffmpeg：使用可能（{self.ffmpeg_path}）")
            self.ffmpeg_status.setStyleSheet("color: #15803d;")
        else:
            self.ffmpeg_status.setText("ffmpeg：未検出。ffmpegをインストールするか、ffmpeg.exeをこのアプリと同じフォルダに置いてください。")
            self.ffmpeg_status.setStyleSheet("color: #b45309;")

    def load_file(self, path: str):
        p = Path(path)
        if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
            QMessageBox.warning(self, "未対応形式", "m4a または mp3 ファイルを選択してください。")
            return
        self.current_file = str(p)
        self.file_label.setText(f"選択中：{p.name}")
        self.load_status_label.setText("⏳ 読み込み中...")
        self.load_status_label.setStyleSheet("font-size: 13px; color: #b45309;")
        self.player.setSource(QUrl.fromLocalFile(str(p)))
        self.play_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)
        self.rewind_btn.setEnabled(True)
        self.forward_btn.setEnabled(True)
        self.browse_btn.setEnabled(True)
        self.preview_start_btn.setEnabled(True)
        self.preview_end_btn.setEnabled(True)
        self.cut_btn.setEnabled(bool(self.ffmpeg_path))
        self.position_slider.setValue(0)
        self.time_label.setText("--:--:-- / --:--:--")
        out = p.with_name(f"{p.stem}_cut{p.suffix}")
        self.output_edit.setText(str(out))
        self.duration_sec = None
        self.update_cut_info()

    def on_duration_changed(self, duration_ms: int):
        if duration_ms > 0:
            self.duration_sec = int(duration_ms / 1000)
            self.position_slider.setRange(0, duration_ms)
            self._update_time_label(0)
            self.load_status_label.setText(f"✅ 読み込み完了（{format_hhmmss(self.duration_sec)}）")
            self.load_status_label.setStyleSheet("font-size: 13px; color: #15803d;")
            if self.duration_sec < time_to_seconds(self.end_edit.time()):
                self.end_edit.setTime(seconds_to_time(self.duration_sec))
            self.update_cut_info()

    def _update_time_label(self, position_ms: int):
        current = format_hhmmss(int(position_ms / 1000))
        total = format_hhmmss(self.duration_sec) if self.duration_sec else "--:--:--"
        self.time_label.setText(f"{current} / {total}")

    def _on_position_changed(self, position_ms: int):
        if not self._seeking:
            self.position_slider.setValue(position_ms)
        self._update_time_label(position_ms)

    def _on_slider_pressed(self):
        self._seeking = True

    def _on_slider_released(self):
        self.player.setPosition(self.position_slider.value())
        self._seeking = False

    def _on_slider_moved(self, value: int):
        self._update_time_label(value)

    def _on_volume_changed(self, value: int):
        self.audio_output.setVolume(value / 100.0)
        self.volume_label.setText(f"{value}%")

    def _on_cut_progress(self, pct: int):
        self.progress.setValue(pct)
        self.progress_label.setText(f"{pct}%")

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            self.play_btn.setText("▶ 再生")
        else:
            self.player.play()
            self.play_btn.setText("⏸ 一時停止")

    def stop_play(self):
        self.player.stop()
        self.play_btn.setText("▶ 再生")

    def rewind(self):
        self.player.setPosition(max(0, self.player.position() - 10_000))

    def fast_forward(self):
        duration = self.player.duration()
        pos = min(duration, self.player.position() + 10_000) if duration > 0 else self.player.position() + 10_000
        self.player.setPosition(pos)

    def seek_and_play(self, sec: int):
        self.player.setPosition(sec * 1000)
        self.player.play()
        self.play_btn.setText("⏸ 一時停止")

    def select_output(self):
        if not self.current_file:
            return
        current = Path(self.output_edit.text()) if self.output_edit.text() else Path(self.current_file)
        suffix = Path(self.current_file).suffix.lower()
        filter_text = "MP3 (*.mp3)" if suffix == ".mp3" else "M4A (*.m4a)"
        path, _ = QFileDialog.getSaveFileName(self, "保存先を選択", str(current), filter_text)
        if path:
            if not path.lower().endswith(suffix):
                path += suffix
            self.output_edit.setText(path)

    def validate(self) -> tuple[bool, str]:
        if not self.current_file:
            return False, "音声ファイルを選択してください。"
        if not self.ffmpeg_path:
            return False, "ffmpegが見つかりません。"
        start = time_to_seconds(self.start_edit.time())
        end = time_to_seconds(self.end_edit.time())
        if end <= start:
            return False, "終了時間は開始時間より後にしてください。"
        if self.duration_sec is not None and end > self.duration_sec:
            return False, "終了時間が音声の長さを超えています。"
        output = self.output_edit.text().strip()
        if not output:
            return False, "保存先を指定してください。"
        if Path(output).suffix.lower() != Path(self.current_file).suffix.lower():
            return False, "保存形式は元ファイルと同じ拡張子にしてください。"
        return True, "OK"

    def update_cut_info(self):
        start = time_to_seconds(self.start_edit.time())
        end = time_to_seconds(self.end_edit.time())
        if end > start:
            self.cut_info.setText(f"切り出し範囲：{format_hhmmss(start)} ～ {format_hhmmss(end)} / 長さ {format_hhmmss(end - start)}")
        else:
            self.cut_info.setText("終了時間は開始時間より後にしてください。")

    def cut_audio(self):
        ok, msg = self.validate()
        if not ok:
            QMessageBox.warning(self, "確認", msg)
            return
        start = time_to_seconds(self.start_edit.time())
        end = time_to_seconds(self.end_edit.time())
        output = self.output_edit.text().strip()
        Path(output).parent.mkdir(parents=True, exist_ok=True)

        self.cut_btn.setEnabled(False)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.progress_label.setText("0%")
        self.progress_label.setVisible(True)

        self.worker = CutWorker(self.ffmpeg_path, self.current_file, output, start, end)
        self.worker.progress.connect(self._on_cut_progress)
        self.worker.finishedOk.connect(self.on_cut_success)
        self.worker.failed.connect(self.on_cut_failed)
        self.worker.start()

    def on_cut_success(self, output: str):
        self.progress.setVisible(False)
        self.progress_label.setVisible(False)
        self.cut_btn.setEnabled(True)
        QMessageBox.information(self, "完了", f"保存しました。\n{output}")

    def on_cut_failed(self, error: str):
        self.progress.setVisible(False)
        self.progress_label.setVisible(False)
        self.cut_btn.setEnabled(True)
        QMessageBox.critical(self, "エラー", f"切り出しに失敗しました。\n\n{error[:2000]}")


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
