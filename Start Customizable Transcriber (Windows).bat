@echo off
rem Double-click to install Customizable Transcriber (first run only) and start it.
rem Python and the app's packages go in a private folder under LOCALAPPDATA, not the app folder:
rem no admin rights, nothing on PATH, and a long or OneDrive-synced app folder can't break them.
setlocal
title Customizable Transcriber
pushd "%~dp0"

set "PYTHONUTF8=1"
set "PYTHON_URL=https://api.nuget.org/v3-flatcontainer/python/3.12.10/python.3.12.10.nupkg"
set "PYTHON_SHA512=bbda4dcf688a94211b62d50968a91b38f305d0b8d1ecd90269f74a86f8a0a4fcebb7ca162a0753a47691eb3df0c964009bd3d8194c6fd19afae8d5fd01e1cc0f"
set "RUNTIME=%LOCALAPPDATA%\Customizable Transcriber\Runtime"
set "BASE_PYTHON=%RUNTIME%\python\tools\python.exe"
set "APP_PYTHON=%RUNTIME%\venv\Scripts\python.exe"
set "INSTALLED_LOCK=%RUNTIME%\venv\installed-requirements.txt"

if not exist "app.py" goto not_extracted

rem Already installed with these exact package versions: just start.
if not exist "%APP_PYTHON%" goto install
if not exist "%INSTALLED_LOCK%" goto install
fc /b "requirements.lock" "%INSTALLED_LOCK%" >nul 2>&1
if not errorlevel 1 goto start

:install
echo.
echo Setting up Customizable Transcriber. This happens once and takes a few minutes.
echo Please leave this window open, and stay connected to the internet.
echo.
if not exist "%RUNTIME%" mkdir "%RUNTIME%"
if exist "%BASE_PYTHON%" goto make_venv

where curl.exe >nul 2>&1
if errorlevel 1 goto windows_too_old
where tar.exe >nul 2>&1
if errorlevel 1 goto windows_too_old

echo Step 1 of 2: downloading Python...
curl.exe --fail --location --silent --show-error --retry 3 --output "%RUNTIME%\python-download.zip" "%PYTHON_URL%"
if errorlevel 1 goto download_failed
certutil -hashfile "%RUNTIME%\python-download.zip" SHA512 | findstr /i /x "%PYTHON_SHA512%" >nul
if errorlevel 1 goto hash_failed
if exist "%RUNTIME%\python-new" rmdir /s /q "%RUNTIME%\python-new"
mkdir "%RUNTIME%\python-new"
tar.exe -xf "%RUNTIME%\python-download.zip" -C "%RUNTIME%\python-new"
if errorlevel 1 goto unpack_failed
if exist "%RUNTIME%\python" rmdir /s /q "%RUNTIME%\python"
move "%RUNTIME%\python-new" "%RUNTIME%\python" >nul
if errorlevel 1 goto unpack_failed
del "%RUNTIME%\python-download.zip"

:make_venv
echo Step 2 of 2: installing the app's components...
"%BASE_PYTHON%" -m venv --clear "%RUNTIME%\venv"
if errorlevel 1 goto packages_failed
"%APP_PYTHON%" -m pip install --quiet --disable-pip-version-check --no-input --only-binary=:all: -r requirements.lock
if errorlevel 1 goto packages_failed
copy /y "requirements.lock" "%INSTALLED_LOCK%" >nul
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
echo If it keeps failing, your network may be blocking api.nuget.org. Send this message to whoever gave you the app.
goto failed

:hash_failed
echo The downloaded copy of Python didn't match the expected file, so it wasn't used. Try again.
echo If it keeps failing, send this message to whoever gave you the app.
del "%RUNTIME%\python-download.zip"
goto failed

:unpack_failed
echo Python couldn't be unpacked. Try again. If it keeps failing, security software may be blocking it.
echo Send this message to whoever gave you the app.
goto failed

:packages_failed
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
