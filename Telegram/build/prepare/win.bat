@echo OFF
set "FullScriptPath=%~dp0"

:: Автоматически откатываем багованный nasm на стабильную версию, чтобы libvpx собрался без ошибок
C:\msys64\usr\bin\bash -lc "pacman -U --noconfirm https://repo.msys2.org/mingw/mingw64/mingw-w64-x86_64-nasm-2.16.03-1-any.pkg.tar.zst" 2>nul

python %FullScriptPath%prepare.py silent %*

if %errorlevel% neq 0 goto error
exit /b
:error
echo FAILED
exit /b 1
