@echo off
setlocal EnableExtensions EnableDelayedExpansion
title EMDASH :: EM Macro Research OS

echo ===============================================
echo    EMDASH  ::  EM Macro Research OS  (launcher)
echo ===============================================
echo.

REM ============================================================================
REM  Finds app.py with ZERO pasting after the first run. Works whether this
REM  .bat sits IN the EMDASH folder or on your DESKTOP, on ANY PC.
REM  Order it tries:
REM    1) app.py right next to this .bat        (in-folder case)
REM    2) a path it REMEMBERED from last time   (saved per-PC)
REM    3) asks you ONCE, then SAVES it forever  (Desktop case, first run only)
REM  The remembered path lives in:  %USERPROFILE%\.emdash_path
REM  (delete that file if you ever move the folder and want it to re-ask)
REM ============================================================================

set "EMROOT="
set "MEMFILE=%USERPROFILE%\.emdash_path"

REM --- 1) is app.py next to this .bat? ---
if exist "%~dp0app.py" (
    set "EMROOT=%~dp0"
    goto :found
)

REM --- 2) did we remember a path last time? ---
if exist "%MEMFILE%" (
    set /p SAVED=<"%MEMFILE%"
    if exist "!SAVED!\app.py" (
        set "EMROOT=!SAVED!\"
        goto :found
    ) else (
        echo (saved path no longer has app.py - will ask again)
        echo.
    )
)

REM --- 3) ask once, validate, then remember it ---
:ask
echo Could not find EMDASH automatically.
echo Paste the full path to your EMDASH folder (the one with app.py):
echo.
set /p EMIN=EMDASH folder: 
REM strip surrounding quotes if the user pasted them
set "EMIN=%EMIN:"=%"
if not exist "%EMIN%\app.py" (
    echo.
    echo   ^>^> No app.py in that folder. Try again.
    echo.
    goto :ask
)
set "EMROOT=%EMIN%\"
REM remember it for next time (no more asking on this PC)
>"%MEMFILE%" echo %EMIN%
echo.
echo   ^>^> Saved. You won't be asked again on this PC.
echo.

:found
cd /d "%EMROOT%"

REM --- pick a Python command: prefer "py", else "python" ---
set "PYCMD="
where py >nul 2>nul && set "PYCMD=py"
if not defined PYCMD ( where python >nul 2>nul && set "PYCMD=python" )
if not defined PYCMD (
    echo ERROR: Python not found on this PC.
    echo Install from https://python.org and tick "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

echo Folder : %EMROOT%
echo Python : %PYCMD%
echo.
echo Starting server...  open  http://127.0.0.1:9001  in your browser.
echo (If the page looks stale, press Ctrl+Shift+R to force-reload.)
echo Press Ctrl+C in THIS window to stop the server.
echo ---------------------------------------------------------------

start "" cmd /c "timeout /t 4 >nul & start "" http://127.0.0.1:9001"

%PYCMD% app.py

echo.
echo ---------------------------------------------------------------
echo [EMDASH stopped.]
pause
