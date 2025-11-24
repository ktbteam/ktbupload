@echo off
title KTB AUTO UPLOADER SYSTEM
color 0A

echo ==================================================
echo      BUOC 1: QUET FOLDER NEN ANH (PREPARE)
echo ==================================================
python prepare_zip.py

echo.
echo ==================================================
echo      BUOC 2: UPLOAD LEN VPS (MAIN PROCESS)
echo ==================================================
python ktb-user-upload.py

echo.
echo ==================================================
echo      HOAN TAT TOAN BO QUY TRINH
echo ==================================================
pause