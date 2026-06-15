# 単純音声ファイル分割ソフト Python版

m4a / mp3 ファイルをドラッグ＆ドロップし、開始時間・終了時間を指定して切り出すWindows向けのシンプルなデスクトップアプリです。

## 主な機能

- m4a / mp3 対応
- ドラッグ＆ドロップ対応
- 開始時間・終了時間を `HH:mm:ss` で指定
- 指定位置の簡易再生確認
- 元ファイルと同じ形式で保存
- ffmpeg の `-c copy` を使うため高速・音質劣化なし

## フォルダ構成

```text
audio_splitter_python/
  main.py
  requirements.txt
  run.bat
  build_exe.bat
  README.md
```

## 事前準備

### 1. Pythonをインストール

Python 3.10以上を推奨します。

### 2. 必要ライブラリをインストール

このフォルダで以下を実行してください。

```bat
pip install -r requirements.txt
```

### 3. ffmpegを用意

以下のどちらかで用意してください。

#### 方法A：ffmpegをPCにインストールしてPATHを通す

`ffmpeg` コマンドが使える状態にします。

#### 方法B：ffmpeg.exeをアプリと同じフォルダに置く

`main.py` と同じ場所に `ffmpeg.exe` を置いても動きます。

## 実行方法

```bat
python main.py
```

または `run.bat` をダブルクリックしてください。

## exe化する場合

```bat
build_exe.bat
```

成功すると `dist` フォルダに実行ファイルが作成されます。

ffmpeg.exeを同梱したい場合は、`main.py` と同じフォルダに `ffmpeg.exe` を置いてから `build_exe.bat` を実行してください。

## 注意点

- `-c copy` は高速ですが、形式や切り出し位置によっては指定位置が数フレーム程度ずれることがあります。
- より正確な位置で切りたい場合は再エンコード方式に変更できますが、処理時間が長くなります。
- まずは「単純・高速・音質劣化なし」を優先した仕様にしています。
