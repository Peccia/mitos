@echo off
setlocal
rem Mitos entrypoint. Routes a verb to the right script with the repo's venv
rem interpreter, so no activation and no remembering which entrypoint owns what:
rem   .\mitos compile ^| deploy ^| review ^| connect --project X ^| sync --machine Y

rem Verbs owned by build\mitos.py (interactive / network reach). Everything else
rem routes to build\compile.py, so a new deterministic verb needs no edit here.
rem Kept in sync with mitos.py's subparsers by test_cli_shim_verbs_match_mitos_py.
set "MITOS_INTERACTIVE_VERBS=init project connect connectors sync"

set "ROOT=%~dp0"
set "PY=%ROOT%build\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=%ROOT%build\.venv\bin\python"
if not exist "%PY%" (
  echo mitos: build\.venv not found, falling back to python on PATH 1>&2
  set "PY=python"
)

set "SCRIPT=%ROOT%build\compile.py"
for %%v in (%MITOS_INTERACTIVE_VERBS%) do if /I "%~1"=="%%v" set "SCRIPT=%ROOT%build\mitos.py"

"%PY%" "%SCRIPT%" %*
exit /b %ERRORLEVEL%
