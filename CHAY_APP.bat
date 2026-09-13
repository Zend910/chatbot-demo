@echo off
cd /d "%~dp0"
if not exist venv (
    echo Chua cai dat! Vui long bam CAI_DAT.bat truoc.
    pause
    exit /b
)
call venv\Scripts\activate.bat
start "" cmd /c "timeout /t 3 >nul && start http://127.0.0.1:5050"
echo Dang khoi dong... trinh duyet se tu mo sau vai giay.
echo (Dung dong cua so nay khi dang dung app. Dong lai la app se tat.)
python app.py
pause
