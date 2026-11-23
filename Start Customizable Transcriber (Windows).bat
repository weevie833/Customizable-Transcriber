@echo off
rem Double-click to install Customizable Transcriber (first run only) and start it.
rem Python and the app's packages go in a private folder under LOCALAPPDATA, not the app folder:
rem no admin rights, nothing on PATH, and a long or OneDrive-synced app folder can't break them.
setlocal
title Customizable Transcriber
pushd "%~dp0"

set "PYTHONUTF8=1"
rem Python is python-build-standalone (Astral), the same build the Mac installer uses, pinned by SHA-256.
rem %%2B is a URL-encoded "+"; a single % would be read as a batch argument.
set "PYTHON_URL=https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.12.16%%2B20261026-x86_64-pc-windows-msvc-install_only.tar.gz"
set "PYTHON_SHA256=590dfcbe3a34c07301e6332e13e2188b98655cd072b08afa45a7998dc4c22bc5"
set "RUNTIME=%LOCALAPPDATA%\Customizable Transcriber\Runtime"
set "BASE_PYTHON=%RUNTIME%\python\python.exe"
set "APP_PYTHON=%RUNTIME%\venv\Scripts\python.exe"
set "INSTALLED_LOCK=%RUNTIME%\venv\installed-requirements.txt"
rem Which Python build is installed (its archive SHA-256). When a newer app version pins a
rem different build, the next start replaces Python instead of keeping the old one forever.
set "BUILD_MARKER=%RUNTIME%\python-build.txt"
rem Written before an update moves anything aside and removed only after every marker is
rem written: if it is still there at the next start, that update failed or was interrupted,
rem and the last working runtime is put back first (CODEX_REVIEW_2.md M-11).
rem Holds "python" (Python and packages being replaced) or "venv" (packages only).
set "PENDING=%RUNTIME%\update-pending.txt"
set "INSTALLED_BUILD="

if not exist "app.py" goto not_extracted

if not exist "%PENDING%" goto no_pending
echo.
echo The last update didn't finish. Putting the previous working setup back first...
call :restore_previous
if errorlevel 1 goto restore_failed
:no_pending
if exist "%BUILD_MARKER%" set /p INSTALLED_BUILD=<"%BUILD_MARKER%"

rem Already installed with this Python and these exact package versions: just start.
if not exist "%APP_PYTHON%" goto install
if /i not "%INSTALLED_BUILD%"=="%PYTHON_SHA256%" goto install
if not exist "%INSTALLED_LOCK%" goto install
fc /b "requirements.lock" "%INSTALLED_LOCK%" >nul 2>&1
if not errorlevel 1 goto start

:install
echo.
echo Setting up Customizable Transcriber. This happens once and takes a few minutes.
echo Please leave this window open, and stay connected to the internet.
echo.
if not exist "%RUNTIME%" mkdir "%RUNTIME%"
if not exist "%BASE_PYTHON%" goto get_python
if /i "%INSTALLED_BUILD%"=="%PYTHON_SHA256%" goto backup_venv

:get_python

where curl.exe >nul 2>&1
if errorlevel 1 goto windows_too_old
where tar.exe >nul 2>&1
if errorlevel 1 goto windows_too_old

echo Step 1 of 2: downloading Python...
curl.exe --fail --location --silent --show-error --retry 3 --output "%RUNTIME%\python-download.tar.gz" "%PYTHON_URL%"
if errorlevel 1 goto download_failed
certutil -hashfile "%RUNTIME%\python-download.tar.gz" SHA256 | findstr /i /x "%PYTHON_SHA256%" >nul
if errorlevel 1 goto hash_failed
if exist "%RUNTIME%\python-new" rmdir /s /q "%RUNTIME%\python-new"
mkdir "%RUNTIME%\python-new"
tar.exe -xf "%RUNTIME%\python-download.tar.gz" -C "%RUNTIME%\python-new"
if errorlevel 1 goto unpack_failed
rem Keep the current runtime until the new one is fully set up, so a failed or interrupted
rem update can go back to it.
call :begin_update python
if errorlevel 1 goto in_use
if not exist "%RUNTIME%\python" goto old_python_moved
move "%RUNTIME%\python" "%RUNTIME%\python-old" >nul
if errorlevel 1 goto in_use_restore
:old_python_moved
if not exist "%RUNTIME%\venv" goto old_venv_moved
move "%RUNTIME%\venv" "%RUNTIME%\venv-old" >nul
if errorlevel 1 goto in_use_restore
:old_venv_moved
move "%RUNTIME%\python-new\python" "%RUNTIME%\python" >nul
if errorlevel 1 goto unpack_failed
rmdir /s /q "%RUNTIME%\python-new"
del "%RUNTIME%\python-download.tar.gz"

goto make_venv

rem Same Python, new package list: keep the working environment until the new one is
rem installed and imports cleanly (reviews/CODEX_REVIEW_8.md M-11).
:backup_venv
if not exist "%RUNTIME%\venv" goto make_venv
call :begin_update venv
if errorlevel 1 goto in_use
move "%RUNTIME%\venv" "%RUNTIME%\venv-old" >nul
if errorlevel 1 goto in_use_restore

:make_venv
echo Step 2 of 2: installing the app's components...
"%BASE_PYTHON%" -m venv --clear "%RUNTIME%\venv"
if errorlevel 1 goto packages_failed
"%APP_PYTHON%" -m pip install --quiet --disable-pip-version-check --no-input --only-binary=:all: -r requirements.lock
if errorlevel 1 goto packages_failed
"%APP_PYTHON%" -c "import google.genai, anthropic, openpyxl, rapidfuzz, PIL, cryptography, certifi"
if errorlevel 1 goto packages_failed
rem The previous runtime is discarded only after both markers are written.
copy /y "requirements.lock" "%INSTALLED_LOCK%" >nul
if errorlevel 1 goto marker_failed
(echo %PYTHON_SHA256%)>"%BUILD_MARKER%"
if errorlevel 1 goto marker_failed
del "%PENDING%" >nul 2>&1
if exist "%RUNTIME%\python-old" rmdir /s /q "%RUNTIME%\python-old"
if exist "%RUNTIME%\venv-old" rmdir /s /q "%RUNTIME%\venv-old"
if exist "%BUILD_MARKER%.old" del "%BUILD_MARKER%.old"
echo Setup is complete.
echo.

:start
if defined CT_INSTALL_ONLY goto done
"%APP_PYTHON%" launch.py --desktop-shortcut
if errorlevel 1 goto app_failed
goto done

:not_extracted
echo This file can't run from inside the ZIP.
echo Right-click the ZIP, choose Extract All, open the extracted folder, and double-click this file there.
goto failed

:windows_too_old
echo This version of Windows is missing tools the installer needs. Windows 10 (2018 or later) or Windows 11 is required.
goto failed

:download_failed
echo Python couldn't be downloaded. Check your internet connection and try again.
echo If it keeps failing, your network may be blocking github.com. Send this message to whoever gave you the app.
goto failed

:hash_failed
echo The downloaded copy of Python didn't match the expected file, so it wasn't used. Try again.
echo If it keeps failing, send this message to whoever gave you the app.
del "%RUNTIME%\python-download.tar.gz"
goto failed

:unpack_failed
call :restore_previous
echo Python couldn't be unpacked. Try again. If it keeps failing, security software may be blocking it.
echo Send this message to whoever gave you the app.
goto failed

:in_use_restore
call :restore_previous
:in_use
echo Python couldn't be updated because it's in use. Close every Customizable Transcriber window, then try again.
goto failed

:restore_failed
echo The previous setup couldn't be put back. Close every Customizable Transcriber window, then try again.
echo If it keeps failing, send this window's text to whoever gave you the app.
goto failed

:marker_failed
call :restore_previous
echo Setup couldn't finish writing its files. Check that your disk isn't full, then try again.
goto failed

:packages_failed
call :restore_previous
echo The app's components couldn't be installed. Check your internet connection and try again.
echo If it keeps failing, your network may be blocking pypi.org. Send this window's text to whoever gave you the app.
goto failed

:app_failed
echo.
echo Customizable Transcriber stopped because of a problem. Send this window's text to whoever gave you the app.
echo If the text says the address is already in use, another copy of the app, or another program, is using port 8765.
goto failed

:failed
echo.
if not defined CT_INSTALL_ONLY pause
popd
exit /b 1

:done
popd
exit /b 0

rem An update failed or was interrupted: put the last working runtime back. The backup
rem returns to the exact path it came from, so the paths inside the virtual environment stay
rem valid. Safe to run at any point of an update, and again after being interrupted.
:restore_previous
set "PENDING_KIND="
if exist "%PENDING%" set /p PENDING_KIND=<"%PENDING%"
if /i "%PENDING_KIND%"=="python" goto restore_python
if /i "%PENDING_KIND%"=="venv" goto restore_venv
goto restore_done
:restore_python
if not exist "%RUNTIME%\python-old" goto restore_python_venv
if exist "%RUNTIME%\python" rmdir /s /q "%RUNTIME%\python"
move "%RUNTIME%\python-old" "%RUNTIME%\python" >nul
if errorlevel 1 exit /b 1
:restore_python_venv
if not exist "%RUNTIME%\venv-old" goto restore_python_marker
if exist "%RUNTIME%\venv" rmdir /s /q "%RUNTIME%\venv"
move "%RUNTIME%\venv-old" "%RUNTIME%\venv" >nul
if errorlevel 1 exit /b 1
:restore_python_marker
if exist "%BUILD_MARKER%.old" goto restore_old_marker
if exist "%BUILD_MARKER%" del "%BUILD_MARKER%"
goto restore_done
:restore_old_marker
move /y "%BUILD_MARKER%.old" "%BUILD_MARKER%" >nul
if errorlevel 1 exit /b 1
goto restore_done
:restore_venv
if not exist "%RUNTIME%\venv-old" goto restore_done
if exist "%RUNTIME%\venv" rmdir /s /q "%RUNTIME%\venv"
move "%RUNTIME%\venv-old" "%RUNTIME%\venv" >nul
if errorlevel 1 exit /b 1
:restore_done
if exist "%PENDING%" del "%PENDING%"
exit /b 0

rem Starts an update of the given kind. Only now may an older backup be discarded, because
rem no update is outstanding (restore_previous ran first if one was).
:begin_update
if exist "%RUNTIME%\python-old" rmdir /s /q "%RUNTIME%\python-old"
if exist "%RUNTIME%\venv-old" rmdir /s /q "%RUNTIME%\venv-old"
if exist "%BUILD_MARKER%.old" del "%BUILD_MARKER%.old"
if not "%~1"=="python" goto begin_write
if not exist "%BUILD_MARKER%" goto begin_write
copy /y "%BUILD_MARKER%" "%BUILD_MARKER%.old" >nul
if errorlevel 1 exit /b 1
:begin_write
rem A successful redirect leaves ERRORLEVEL as it was (often 1 from the fc compare that
rem started this update), so check that the marker exists instead.
(echo %~1)>"%PENDING%"
if not exist "%PENDING%" exit /b 1
exit /b 0
