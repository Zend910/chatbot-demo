@echo off
cd /d "%~dp0"

echo === Xoa moi truong ao cu (neu co) de cai lai tu dau cho sach ===
if exist venv (
    rd /s /q venv
)

echo === Dang tao moi truong ao moi ===
python -m venv venv
call venv\Scripts\activate.bat

echo === Nang cap pip ===
python -m pip install --upgrade pip

echo === Dang cai thu vien (uu tien ban co san, khong tu bien dich) ===
pip install --prefer-binary -r requirements.txt
if errorlevel 1 (
    echo.
    echo ===================================================
    echo   CAI DAT BI LOI. Chup lai toan bo man hinh loi mau
    echo   do o tren va gui cho Claude de kiem tra tiep.
    echo ===================================================
    pause
    exit /b 1
)

echo.
echo ===================================================
echo   CAI DAT XONG! Tu gio chi can bam CHAY_APP.bat
echo ===================================================
pause
