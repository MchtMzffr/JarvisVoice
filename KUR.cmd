@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "JARVIS_PACKAGE_DIR=%~dp0"
set "UV_PYTHON_INSTALL_DIR=%~dp0.runtime\python"
set "UV_PYTHON_BIN_DIR=%~dp0.runtime\bin"
set "UV_CACHE_DIR=%~dp0.runtime\cache"
set "UV_LINK_MODE=copy"
set "PYTHONUTF8=1"
set "ORT_DISABLE_TELEMETRY=1"
set "HF_HUB_DISABLE_TELEMETRY=1"
set "HF_HUB_DISABLE_IMPLICIT_TOKEN=1"
echo Jarvis Voice 0.3.0 - masaustu kurulumu
echo Mevcut Ollama ve GPT-OSS kullanilir; eksikse kurulum tamamlanir.
echo Model yoksa yaklasik 13 GB indirme ve ek disk alani gerekir.
echo Kurulumdan once acik Jarvis penceresini kapat.
echo Ilk kurulumda Python, masaustu paketleri ve yaklasik 525 MB ses modeli indirilir.
echo.
if not exist ".venv\Scripts\python.exe" goto idle_checked
".venv\Scripts\python.exe" update_jarvis.py --check-idle
if errorlevel 1 goto fail
:idle_checked
if not exist ".runtime" mkdir ".runtime"
if exist ".runtime\uv.exe" goto dependencies
echo Uygulamaya ozel kurulum araci indiriliyor...
powershell.exe -NoProfile -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $dir=Join-Path $env:JARVIS_PACKAGE_DIR '.runtime'; $zip=Join-Path $dir 'uv-windows.zip'; Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/astral-sh/uv/releases/download/0.13.9/uv-x86_64-pc-windows-msvc.zip' -OutFile $zip; $hash=(Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash; if($hash -ne 'EDD61F7F5728A56CC62455386661860BDFC7BAB65872F39B0C25BDCC1D8E1BEB'){throw 'Kurulum araci SHA256 dogrulamasi basarisiz.'}; $out=Join-Path $dir 'uv-unpacked'; Expand-Archive -LiteralPath $zip -DestinationPath $out -Force; $bin=Get-ChildItem -LiteralPath $out -Filter 'uv.exe' -File -Recurse | Select-Object -First 1; if($null -eq $bin){throw 'uv.exe arsivde bulunamadi.'}; Copy-Item -LiteralPath $bin.FullName -Destination (Join-Path $dir 'uv.exe') -Force"
if errorlevel 1 goto fail
:dependencies
echo Python 3.11 ve sabitlenmis CPU paketleri kuruluyor...
".runtime\uv.exe" sync --frozen --extra desktop --python 3.11.18 --no-dev
if errorlevel 1 goto fail
echo Yerel yapay zeka ve masaustu bilesenleri kontrol ediliyor...
".venv\Scripts\python.exe" -m jarvis.setup_local --install-missing
if errorlevel 1 goto fail
echo Ses modeli dosyalari hazirlaniyor...
".venv\Scripts\python.exe" -m jarvis.prepare
if errorlevel 1 goto fail
echo Kurulumun gercek model yukleme kontrolu yapiliyor...
".venv\Scripts\python.exe" -m jarvis.verify
if errorlevel 1 goto fail
echo.
echo Kurulum tamamlandi. BASLAT.cmd dosyasini acabilirsin.
if /I not "%~1"=="--no-pause" pause
exit /b 0
:fail
echo.
echo Kurulum tamamlanamadi. Yukaridaki son hata metnini paylas.
echo DLL yukleme hatasi varsa Microsoft Visual C++ x64 runtime gerekebilir.
echo Ayrinti icin yukaridaki hata mesajini kontrol et. KUR.cmd yeniden calistirilabilir.
if /I not "%~1"=="--no-pause" pause
exit /b 1
