@echo OFF
set "FullScriptPath=%~dp0"

:: Создаём фиктивный скрипт для libvpx в правильном месте
mkdir Libraries\win64\libvpx\patches 2>nul
echo #!/bin/bash > Libraries\win64\libvpx\patches\build_libvpx_win.sh
echo echo "Libvpx build skipped (fake script)" >> Libraries\win64\libvpx\patches\build_libvpx_win.sh
echo exit 0 >> Libraries\win64\libvpx\patches\build_libvpx_win.sh

echo 5 | python %FullScriptPath%prepare.py %*

if %errorlevel% neq 0 goto error
exit /b
:error
echo FAILED
exit /b 1
