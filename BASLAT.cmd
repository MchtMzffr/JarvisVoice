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
echo Jarvis Voice aciliyor. Ollama uygulamasi acik olmali.
echo Bu pencereyi acik birak. Kapatmak icin Ctrl+C kullan.
".venv\Scripts\python.exe" -m jarvis
if errorlevel 1 pause
exit /b
:missing
echo Once KUR.cmd dosyasini calistir.
pause
exit /b 1

:updating
echo Guncelleme suruyor veya yarida kaldi. Guncelleme penceresindeki sonucu kontrol et.
echo Sorun surerse README icindeki guncelleme kurtarma adimlarini izle.
pause
exit /b 1
