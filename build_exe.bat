@echo off
cd /d %~dp0
pip install -r requirements.txt

if exist ffmpeg.exe (
  pyinstaller --noconfirm --onefile --windowed --name AudioSplitter --add-binary "ffmpeg.exe;." main.py
) else (
  pyinstaller --noconfirm --onefile --windowed --name AudioSplitter main.py
)

pause
