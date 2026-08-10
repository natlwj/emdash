@echo off
REM ===================================================================
REM  EMDASH_desktop.bat  --  DESKTOP double-click launcher
REM
REM  Unlike EMDASH.bat (which lives INSIDE the EMDASH folder and uses its
REM  own location), THIS file is meant to sit on your DESKTOP -- so it has
REM  to be TOLD where the EMDASH folder is. It works on BOTH your PCs by
REM  trying a list of known locations and using the first one that has app.py.
REM
REM  ============ HOW TO USE ON A NEW MACHINE ============
REM  If it says "could not find EMDASH", just add that machine's path to the
REM  CANDIDATES list below (copy a line, paste the folder path). That's it.
REM  You can also set an EMDASH_HOME environment variable and it wins over all.
REM
REM  TO STOP: close this black window, or press Ctrl+C in it.
REM ===================================================================

title EMDASH - EM Macro Research OS
color 0F
setlocal EnableDelayedExpansion

echo.
echo   ===============================================
echo     EMDASH  ::  EM Macro Research OS  (desktop launcher)
echo   ===============================================
echo.

REM ===================================================================
REM  1) WHERE IS EMDASH?  -- checked in this order, first hit wins.
REM     Edit / add lines here for each machine. Keep the quotes.
REM ===================================================================
set "EMDASH_DIR="

REM ---- (a) explicit override via environment variable, if you set one ----
if defined EMDASH_HOME if exist "%EMDASH_HOME%\app.py" set "EMDASH_DIR=%EMDASH_HOME%"

REM ---- (b) known locations. ADD YOUR OWN PATHS HERE (one per line). ----
call :try "C:\Users\Intern2\GembridgeCapitalManagementPte Ltd\GembridgeShare - Research\Intern Projects\Nathaniel\EMDASH"
call :try "%USERPROFILE%\EMDASH"
call :try "%USERPROFILE%\Desktop\EMDASH"
call :try "%USERPROFILE%\Documents\EMDASH"
call :try "%USERPROFILE%\source\repos\EMDASH"
call :try "%USERPROFILE%\Projects\EMDASH"
call :try "C:\EMDASH"
call :try "D:\EMDASH"

REM ---- (c) last resort: ask the user to type/paste the folder path ----
if not defined EMDASH_DIR (
    echo   Could not find EMDASH automatically.
    echo   Paste the full path to your EMDASH folder ^(the one with app.py^)
    echo   then press Enter:
    echo.
    set /p "EMDASH_DIR=   EMDASH folder: "
    REM strip surrounding quotes if the user pasted them
    set "EMDASH_DIR=!EMDASH_DIR:"=!"
)

if not defined EMDASH_DIR goto :notfound
if not exist "%EMDASH_DIR%\app.py" goto :notfound

echo   Folder : %EMDASH_DIR%

REM ===================================================================
REM  2) FIND PYTHON: py launcher first, then plain python.
REM ===================================================================
set "PYEXE="
where py >nul 2>&1 && set "PYEXE=py"
if not defined PYEXE (
    where python >nul 2>&1 && set "PYEXE=python"
)
if not defined PYEXE (
    echo.
    echo   [ERROR] No Python found on PATH.
    echo   Install Python, or set PYEXE below to your python.exe full path, e.g.:
    echo       set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
    echo.
    pause
    exit /b 1
)
echo   Python : %PYEXE%
echo.

REM ===================================================================
REM  3) LAUNCH.
REM ===================================================================
cd /d "%EMDASH_DIR%"

REM quiet the harmless urllib3/chardet version warning
set PYTHONWARNINGS=ignore

REM open the browser ~4s from now, once the server is up
start "" /min cmd /c "timeout /t 4 /nobreak >nul & start http://127.0.0.1:9001"

echo   Starting server...  browser will open in a few seconds.
echo   (If the page looks stale, press Ctrl+Shift+R to force-reload the CSS.)
echo   ---------------------------------------------------------------
echo.

%PYEXE% app.py

REM ---- server stopped: keep the window open so errors are readable ----
echo.
echo   ---------------------------------------------------------------
if errorlevel 1 (
    echo   [EMDASH stopped with an ERROR - the traceback is above.]
    echo.
    echo   Common fixes:
    echo     * missing package   ^-^>  %PYEXE% -m pip install dash plotly pandas feedparser requests
    echo     * port 9001 in use   ^-^>  close the other EMDASH window
    echo     * no data            ^-^>  %PYEXE% ingest.py
) else (
    echo   [EMDASH stopped normally.]
)
echo.
pause
exit /b 0

REM ===================================================================
REM  helper: set EMDASH_DIR to %~1 if it contains app.py and none set yet
REM ===================================================================
:try
if defined EMDASH_DIR goto :eof
if exist "%~1\app.py" set "EMDASH_DIR=%~1"
goto :eof

:notfound
echo.
echo   [ERROR] Could not locate the EMDASH folder (the one containing app.py).
echo.
echo   Fix: open this .bat in Notepad and add your machine's path to the
echo   CANDIDATES list near the top, for example:
echo       call :try "C:\path\to\your\EMDASH"
echo.
pause
exit /b 1
