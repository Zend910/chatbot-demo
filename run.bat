@echo off
cd /d "%~dp0"

if not exist venv (
    echo Dang tao moi truong ao...
    python -m venv venv
)

call venv\Scripts\activate.bat

if not exist venv\installed.ok (
    echo Dang cai thu vien can thiet, cho mot chut...
    pip install --prefer-binary -r requirements.txt
    if errorlevel 1 (
        echo.
        echo ============================================================
        echo  CAI THU VIEN BI LOI. App chua the chay duoc.
        echo  Doc thong bao loi mau do o tren de biet nguyen nhan.
        echo  Sau khi sua xong, chay lai file nay (run.bat) de thu lai.
        echo ============================================================
        pause
        exit /b 1
    )
    echo ok > venv\installed.ok
)

start "" http://127.0.0.1:5050
python app.py

pause
