@echo off
REM ===================================================================
REM  EMDASH  --  double-click launcher
REM
REM  WHAT THIS DOES
REM    1. jumps to whatever folder this .bat is sitting in  (%~dp0)
REM    2. finds a working Python  (py launcher first, then python)
REM    3. starts app.py
REM    4. opens your browser at the dashboard
REM    5. leaves the window open if anything goes wrong, so you can
REM       actually read the error instead of watching it flash past
REM
REM  PATH IS DYNAMIC.  Nothing is hardcoded to Intern2 -- %~dp0 is
REM  "the directory this script lives in", so this works on any PC and
REM  under any username as long as the .bat sits in the EMDASH folder.
REM
REM  TO STOP THE DASHBOARD: close this black window, or press Ctrl+C in it.
REM ===================================================================

title EMDASH - EM Macro Research OS
color 0F

cd /d "%~dp0"

echo.
echo   ===============================================
echo     EMDASH  ::  EM Macro Research OS
echo   ===============================================
echo.
echo   Folder : %CD%
echo.

REM ---- sanity check: are we actually in the EMDASH folder? ----
if not exist "app.py" (
    echo   [ERROR] app.py not found in this folder.
    echo.
    echo   This .bat must live in the EMDASH folder, next to app.py.
    echo   Move it there and double-click it again.
    echo.
    pause
    exit /b 1
)

REM ---- find Python: try the py launcher first, then plain python ----
set "PYEXE="
where py >nul 2>&1 && set "PYEXE=py"
if not defined PYEXE (
    where python >nul 2>&1 && set "PYEXE=python"
)
if not defined PYEXE (
    echo   [ERROR] No Python found on PATH.
    echo.
    echo   Install Python, or open this file and set PYEXE to the full
    echo   path of your python.exe, for example:
    echo       set "PYEXE=C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python314\python.exe"
    echo.
    pause
    exit /b 1
)

echo   Python : %PYEXE%
echo.

REM ---- quiet the harmless urllib3/chardet version warning ----
set PYTHONWARNINGS=ignore

REM ---- open the browser ~4s from now, so the server is up first ----
start "" /min cmd /c "timeout /t 4 /nobreak >nul & start http://127.0.0.1:9001"

echo   Starting server...  browser will open in a few seconds.
echo   (If the page looks stale, press Ctrl+Shift+R to force-reload the CSS.)
echo.
echo   ---------------------------------------------------------------
echo.

%PYEXE% app.py

REM ---- if we land here the server stopped; hold the window open ----
echo.
echo   ---------------------------------------------------------------
echo.
if errorlevel 1 (
    echo   [EMDASH stopped with an ERROR - the traceback is above.]
    echo.
    echo   Common fixes:
    echo     * missing package   ^-^>  %PYEXE% -m pip install dash plotly pandas feedparser requests
    echo     * port 9001 in use  ^-^>  close the other EMDASH window
    echo     * no data           ^-^>  %PYEXE% ingest.py
) else (
    echo   [EMDASH stopped normally.]
)
echo.
pause
