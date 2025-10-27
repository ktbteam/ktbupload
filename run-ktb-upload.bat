@echo off

REM --- Quan trong: Di chuyen den thu muc chua file .bat nay ---
REM --- (Fix loi 'system32' khi 'Run as administrator') ---
cd /d "%~dp0"

REM -------------------------------------------------------------

echo --- Bat dau quy trinh KTB Upload ---
echo.
echo Dang chay tu thu muc: %cd%
echo.
python ktb-admin-upload.py

echo.
echo --- Qua trinh hoan tat. ---
pause