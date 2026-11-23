@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "ORT_DISABLE_TELEMETRY=1"
set "HF_HUB_DISABLE_TELEMETRY=1"
set "HF_HUB_DISABLE_IMPLICIT_TOKEN=1"
if exist ".jarvis-update.lock" goto updating
if not exist ".venv\Scripts\python.exe" goto missing
if not exist "data\prepared.json" goto missing
echo Jarvis Voice masaustu penceresi aciliyor.
echo Yerel Ollama arka planda kullanilir. Jarvis penceresini kapatarak cikabilirsin.
".venv\Scripts\python.exe" -m jarvis.setup_local
if errorlevel 1 goto failed
start "" /D "%~dp0" "%~dp0.venv\Scripts\pythonw.exe" -m jarvis --desktop
if errorlevel 1 goto failed
exit /b 0
:failed
echo Jarvis baslatilamadi. Yukaridaki aciklamayi kontrol et.
pause
exit /b 1
:missing
echo Once KUR.cmd dosyasini calistir.
pause
exit /b 1

:updating
echo Guncelleme suruyor veya yarida kaldi. Guncelleme penceresindeki sonucu kontrol et.
echo Sorun surerse README icindeki guncelleme kurtarma adimlarini izle.
pause
exit /b 1
