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
    QStyle,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

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


class DropArea(QFrame):
    fileDropped = Signal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setObjectName("DropArea")
        self.setMinimumHeight(150)
        self.label = QLabel("ここに m4a / mp3 ファイルをドラッグ＆ドロップ\nまたはクリックして選択")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("font-size: 18px; color: #334155;")
        layout = QVBoxLayout(self)
        layout.addWidget(self.label)

    def mousePressEvent(self, event):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "音声ファイルを選択",
            "",
            "音声ファイル (*.m4a *.mp3)",
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


class CutWorker(QThread):
    finishedOk = Signal(str)
    failed = Signal(str)

    def __init__(self, ffmpeg_path: str, input_file: str, output_file: str, start_sec: int, end_sec: int):
        super().__init__()
        self.ffmpeg_path = ffmpeg_path
        self.input_file = input_file
        self.output_file = output_file
        self.start_sec = start_sec
        self.end_sec = end_sec

    def run(self):
        try:
            command = [
                self.ffmpeg_path,
                "-y",
                "-ss",
                format_hhmmss(self.start_sec),
                "-to",
                format_hhmmss(self.end_sec),
                "-i",
                self.input_file,
                "-c",
                "copy",
                self.output_file,
            ]
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if result.returncode == 0 and Path(self.output_file).exists():
                self.finishedOk.emit(self.output_file)
            else:
                self.failed.emit(result.stderr or "ffmpegの実行に失敗しました。")
        except Exception as e:
            self.failed.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("単純音声ファイル分割ソフト")
        self.resize(760, 560)

        self.ffmpeg_path = find_ffmpeg()
        self.current_file: str | None = None
        self.duration_sec: int | None = None
        self.worker: CutWorker | None = None

        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(0.8)
        self.player.durationChanged.connect(self.on_duration_changed)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setSpacing(14)

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

        row = QHBoxLayout()
        self.play_btn = QPushButton("再生")
        self.play_btn.clicked.connect(self.toggle_play)
        self.play_btn.setEnabled(False)
        row.addWidget(self.play_btn)

        self.stop_btn = QPushButton("停止")
        self.stop_btn.clicked.connect(self.stop_play)
        self.stop_btn.setEnabled(False)
        row.addWidget(self.stop_btn)

        self.duration_label = QLabel("再生時間：--:--:--")
        row.addWidget(self.duration_label)
        row.addStretch()
        layout.addLayout(row)

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

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

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
        self.player.setSource(QUrl.fromLocalFile(str(p)))
        self.play_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)
        self.browse_btn.setEnabled(True)
        self.preview_start_btn.setEnabled(True)
        self.preview_end_btn.setEnabled(True)
        self.cut_btn.setEnabled(bool(self.ffmpeg_path))

        out = p.with_name(f"{p.stem}_cut{p.suffix}")
        self.output_edit.setText(str(out))
        self.duration_sec = None
        self.duration_label.setText("再生時間：読み込み中...")
        self.update_cut_info()

    def on_duration_changed(self, duration_ms: int):
        if duration_ms > 0:
            self.duration_sec = int(duration_ms / 1000)
            self.duration_label.setText(f"再生時間：{format_hhmmss(self.duration_sec)}")
            if self.duration_sec < time_to_seconds(self.end_edit.time()):
                self.end_edit.setTime(seconds_to_time(self.duration_sec))
            self.update_cut_info()

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            self.play_btn.setText("再生")
        else:
            self.player.play()
            self.play_btn.setText("一時停止")

    def stop_play(self):
        self.player.stop()
        self.play_btn.setText("再生")

    def seek_and_play(self, sec: int):
        self.player.setPosition(sec * 1000)
        self.player.play()
        self.play_btn.setText("一時停止")

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
        self.progress.setVisible(True)
        self.worker = CutWorker(self.ffmpeg_path, self.current_file, output, start, end)
        self.worker.finishedOk.connect(self.on_cut_success)
        self.worker.failed.connect(self.on_cut_failed)
        self.worker.start()

    def on_cut_success(self, output: str):
        self.progress.setVisible(False)
        self.cut_btn.setEnabled(True)
        QMessageBox.information(self, "完了", f"保存しました。\n{output}")

    def on_cut_failed(self, error: str):
        self.progress.setVisible(False)
        self.cut_btn.setEnabled(True)
        QMessageBox.critical(self, "エラー", f"切り出しに失敗しました。\n\n{error[:2000]}")


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
