@echo off
rem ===========================================================================
rem  Trinity - local one-click start
rem
rem  WHAT IT DOES : starts the FastAPI backend (uvicorn) in this window.
rem  WHAT IT DOES NOT : it does not start the UI. The UI is a separate Node
rem                 project (web-react) and there is no Python UI anymore -
rem                 the Streamlit console (ui/) was deleted on 2026-09-27.
rem
rem  USAGE
rem     start.bat                start API only (default: port 8001)
rem     start.bat both           API here + a second window running npm run dev
rem     start.bat check          print what would run, start nothing (touches no port)
rem     start.bat api 8000       same as default but on another port
rem     set PY=D:\some\python.exe && start.bat   force a specific interpreter
rem
rem  WHY 8001 : web-react\vite.config.ts hardcodes API_TARGET = 
rem             http://127.0.0.1:8001, while config.py's api_port default is 8000
rem             (that is the Docker path: compose maps API_PORT:-8000 to 8000).
rem             The proxy target is not auto-detected - move the backend and you
rem             must move that one line in web-react\vite.config.ts as well.
rem
rem  TWO DELIBERATE CHOICES
rem   1) No --reload. Reload spawns a child process, so the thread pool and the
rem      task queue each exist twice - behaviour goes weird and is very hard to
rem      trace. Restart this window after editing code instead.
rem   2) Binds 127.0.0.1 only. There is no user system. If you expose the port,
rem      set API_AUTH_TOKEN first - and know that web-react cannot send a Bearer
rem      token today (docs/known_residuals.md R-12), so a token-protected
rem      backend is unreachable from that UI.
rem
rem  This file is ASCII on purpose: cmd.exe reads .bat in the OEM codepage, so
rem  accented/CJK text here would render as mojibake in the comments.
rem ===========================================================================

setlocal
cd /d "%~dp0"

set "MODE=api"
set "PORT=8001"

rem arg1 = mode (api | both | check), arg2 = port. An unknown mode ABORTS:
rem silently falling back to "api" would mean a typo starts a server.
if "%~1"=="" goto mode_ok
if /I "%~1"=="api"   set "MODE=api"   & goto mode_ok
if /I "%~1"=="both"  set "MODE=both"  & goto mode_ok
if /I "%~1"=="check" set "MODE=check" & goto mode_ok
echo [error] unknown mode "%~1".
echo [error] usage:  start.bat [api ^| both ^| check] [port]
echo [error]   api   - API only in this window (default)
echo [error]   both  - API here + a second window running npm run dev
echo [error]   check - print the two commands, start nothing
exit /b 2
:mode_ok
if not "%~2"=="" set "PORT=%~2"

rem a port is digits only - uvicorn would otherwise fail with a message that
rem looks like a networking problem, not like "you passed the word `check`".
set "BADPORT="
for /f "delims=0123456789" %%A in ("%PORT%") do set "BADPORT=%%A"
if defined BADPORT (
  echo [warn] second argument "%PORT%" is not a port number - using 8001.
  set "PORT=8001"
)

rem ----------------------------------------------------------------- interpreter
rem Order: %PY% (explicit override) > .venv > python on PATH > py launcher.
rem .venv is preferred when present; scripts\start_api.py used to shell out to it
rem and that subprocess dies under this machine's app-control policy, so this
rem script runs uvicorn **in the current process tree** instead.
set "PYEXE="
if defined PY set "PYEXE=%PY%"
if not defined PYEXE if exist ".venv\Scripts\python.exe" set "PYEXE=%~dp0.venv\Scripts\python.exe"
if defined PYEXE goto py_found
where python >nul 2>&1
if not errorlevel 1 set "PYEXE=python"
if defined PYEXE goto py_found
where py >nul 2>&1
if not errorlevel 1 set "PYEXE=py"
:py_found
if not defined PYEXE goto no_python

echo.
echo [api ] interpreter : %PYEXE%
echo [api ] bind         : http://127.0.0.1:%PORT%  (no reload, no auth unless API_AUTH_TOKEN is set)
echo [ui  ] web-react    : cd web-react ^&^& npm run dev   (dev server on http://127.0.0.1:5173)

if not "%MODE%"=="check" goto preflight
echo.
echo [check] nothing started. The two commands would have been:
echo [check]   "%PYEXE%" -m uvicorn api.main:app --host 127.0.0.1 --port %PORT%
echo [check]   npm run dev   in "%~dp0web-react"
goto done

:preflight
"%PYEXE%" -c "import uvicorn, api.main" >nul 2>&1
if errorlevel 1 (
  echo.
  echo [error] "%PYEXE%" cannot import uvicorn or api.main.
  echo [error] Install the deps into that interpreter:
  echo [error]   "%PYEXE%" -m pip install -e ".[dev]"
  echo [error] If you expected .venv: it must contain uvicorn, not just Python.
  exit /b 1
)

if not "%MODE%"=="both" goto start_api
where npm >nul 2>&1
if errorlevel 1 (
  echo.
  echo [warn] npm not on PATH - starting the API only. Start the UI yourself:
  echo [warn]   cd web-react ^&^& npm install ^&^& npm run dev
) else (
  start "Trinity web-react dev" /D "%~dp0web-react" cmd /k npm run dev
  echo.
  echo [ui  ] opened a second window running "npm run dev" in web-react.
)

:start_api
echo.
echo [api ] starting - Ctrl+C stops it, closing this window stops it too.
"%PYEXE%" -m uvicorn api.main:app --host 127.0.0.1 --port %PORT%
goto done

:no_python
echo.
echo [error] No Python found: neither .venv\Scripts\python.exe nor python/py on PATH.
echo [error] Create the venv first (see README, "local start") or put Python on PATH.
exit /b 1

:done
endlocal
