@echo off
echo ============================================
echo  Building WarrantyTracker.exe  (one-time step)
echo ============================================
echo.
echo Installing required packages...
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Something went wrong installing packages. Make sure Python is
    echo installed and on PATH, then try again.
    pause
    exit /b 1
)

echo.
echo Building the .exe (this can take a minute)...
pyinstaller --onefile --console --name WarrantyTracker ^
    --add-data "public;public" ^
    --add-data "warranty.db;." ^
    app.py

echo.
if exist "dist\WarrantyTracker.exe" (
    echo ============================================
    echo  Done! Your app is here:
    echo  dist\WarrantyTracker.exe
    echo.
    echo  Copy that file anywhere you like (Desktop, etc.)
    echo  and double-click it any time you want to run
    echo  WarrantIQ. No Python or command prompt needed.
    echo ============================================
) else (
    echo Build did not produce an exe - scroll up to check for errors.
)
pause
