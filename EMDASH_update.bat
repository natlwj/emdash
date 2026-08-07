@echo off
REM ===================================================================
REM EMDASH_update.bat  --  the SCHEDULED pull (weekly, unattended)
REM
REM Companion to EMDASH.bat (which launches the dashboard) and to the
REM in-app "Update" buttons (runner.py, for manual pulls while the app
REM is open). THIS file is for Windows Task Scheduler: it runs the data
REM collectors with NO dashboard and NO window interaction, and appends
REM a timestamped line to update_log.txt so you can see it ran.
REM
REM WHAT IT DOES, in order:
REM   1. news_ingest.py     -- fresh headlines (RSS + GDELT)
REM   2. ingest.py          -- macro + markets (skips what's current)
REM Both use skip_existing, so a weekly run is cheap: it only fills gaps
REM and appends new dates. It never re-pulls the whole history.
REM
REM CONVENTIONS (mirrors EMDASH.bat):
REM   * %~dp0 = this file's own folder, so it works for any user with no
REM     hardcoded path (Intern2 today, whoever inherits it tomorrow).
REM   * tries the 'py' launcher first, then 'python' on PATH.
REM   * silences the harmless urllib3/chardet RequestsDependencyWarning.
REM
REM SET IT UP (once) -- Windows Task Scheduler:
REM   Task Scheduler > Create Basic Task
REM     Name:    EMDASH weekly update
REM     Trigger: Weekly  (pick a day/time the laptop is on, e.g. Mon 08:00)
REM     Action:  Start a program
REM     Program: <full path to this file>\EMDASH_update.bat
REM     Finish. (Tick "Run whether user is logged on or not" if you like.)
REM   That's it -- the pull now runs itself every week and logs the result.
REM
REM RUN IT BY HAND to test:  just double-click this file, or from a shell:
REM   .\EMDASH_update.bat
REM ===================================================================

setlocal
cd /d "%~dp0"

REM ---- silence the noisy (harmless) requests dependency warning ----
set PYTHONWARNINGS=ignore::UserWarning

REM ---- find a Python: prefer the 'py' launcher, fall back to python ----
set PYEXE=
where py >nul 2>nul && set PYEXE=py
if not defined PYEXE (
    where python >nul 2>nul && set PYEXE=python
)
if not defined PYEXE (
    echo [EMDASH_update] ERROR: no Python found on PATH ^(tried 'py' and 'python'^).
    echo [EMDASH_update] Install Python or add it to PATH, then re-run.
    exit /b 9
)

set LOG=%~dp0update_log.txt
echo. >> "%LOG%"
echo ================================================================ >> "%LOG%"
echo [EMDASH_update] START  %DATE% %TIME%  using %PYEXE% >> "%LOG%"
echo ---------------------------------------------------------------- >> "%LOG%"

REM ---- 1) NEWS -----------------------------------------------------
echo [EMDASH_update] (1/2) news_ingest.py ...
echo [EMDASH_update] (1/2) news_ingest.py >> "%LOG%"
%PYEXE% "%~dp0news_ingest.py" >> "%LOG%" 2>&1
set RC_NEWS=%ERRORLEVEL%
echo [EMDASH_update]     news exit code = %RC_NEWS% >> "%LOG%"

REM ---- 2) MACRO + MARKETS -----------------------------------------
echo [EMDASH_update] (2/2) ingest.py ...
echo [EMDASH_update] (2/2) ingest.py >> "%LOG%"
%PYEXE% "%~dp0ingest.py" >> "%LOG%" 2>&1
set RC_ING=%ERRORLEVEL%
echo [EMDASH_update]     ingest exit code = %RC_ING% >> "%LOG%"

echo ---------------------------------------------------------------- >> "%LOG%"
if "%RC_NEWS%"=="0" if "%RC_ING%"=="0" (
    echo [EMDASH_update] DONE OK  %DATE% %TIME% >> "%LOG%"
    echo [EMDASH_update] done -- both pulls succeeded. See update_log.txt.
    endlocal & exit /b 0
)
echo [EMDASH_update] DONE WITH ERRORS  news=%RC_NEWS% ingest=%RC_ING%  %DATE% %TIME% >> "%LOG%"
echo [EMDASH_update] finished with errors ^(news=%RC_NEWS% ingest=%RC_ING%^). See update_log.txt.
endlocal & exit /b 1
