@echo off
REM Settlement statement generator - Windows entry point.
REM Same arguments as make_settlement.py, see references\engine-spec.md
REM   scripts\settle.bat --input business.json --png --clipboard --brief
setlocal
set "SD=%~dp0"
set "PKG=%SD%.."
set "PYEXE="
set "PYPRE="

if exist "%PKG%\.venv\Scripts\python.exe" (
  set "PYEXE=%PKG%\.venv\Scripts\python.exe"
  goto RUN
)
where py >nul 2>nul
if not errorlevel 1 (
  set "PYEXE=py"
  set "PYPRE=-3"
  goto RUN
)
where python >nul 2>nul
if not errorlevel 1 (
  set "PYEXE=python"
  goto RUN
)
echo [settlement] Python not found. Please run install.bat first.
exit /b 127

:RUN
"%PYEXE%" %PYPRE% "%SD%make_settlement.py" %*
exit /b %errorlevel%
