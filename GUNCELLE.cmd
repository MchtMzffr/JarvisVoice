@echo off
setlocal
chcp 65001 >nul
set "JARVIS_UPDATE_SOURCE=%~dp0"
set "PYTHONUTF8=1"
echo Jarvis Voice 0.3.0 - mevcut kurulumu guncelle
echo Once Jarvis penceresini kapat; eski terminal surumunde Ctrl+C kullan.
echo Acilan pencereden CALISAN ESKI klasordeki BASLAT.cmd dosyasini sec.
echo.
powershell.exe -NoProfile -STA -Command "$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.Windows.Forms; $dialog=New-Object System.Windows.Forms.OpenFileDialog; $dialog.Title='Mevcut Jarvis kurulumundaki BASLAT.cmd dosyasini sec'; $dialog.Filter='Jarvis baslaticisi (BASLAT.cmd)|BASLAT.cmd'; $dialog.CheckFileExists=$true; if($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK){Write-Host 'Guncelleme iptal edildi.'; exit 2}; if([IO.Path]::GetFileName($dialog.FileName) -ine 'BASLAT.cmd'){throw 'BASLAT.cmd dosyasi secilmeli.'}; $target=[IO.Path]::GetDirectoryName($dialog.FileName); $python=Join-Path $target '.venv\Scripts\python.exe'; $updater=Join-Path $env:JARVIS_UPDATE_SOURCE 'update_jarvis.py'; if(-not(Test-Path -LiteralPath $python -PathType Leaf)){throw 'Bu klasorde tamamlanmis Jarvis kurulumu bulunamadi.'}; & $python $updater --target $target; if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}; Write-Host 'Kod guncellendi. Masaustu paketleri ve yerel modeller kontrol ediliyor.'; & (Join-Path $target 'KUR.cmd') --no-pause; exit $LASTEXITCODE"
if errorlevel 1 goto fail
echo.
echo Guncelleme basarili. Eski kurulum klasorundeki BASLAT.cmd ile devam et.
pause
exit /b 0
:fail
echo.
echo Guncelleme tamamlanmadi. Yukaridaki aciklamayi kontrol et.
pause
exit /b 1
