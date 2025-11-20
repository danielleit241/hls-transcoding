@echo off
echo Starting Firebase Emulators and creating storage structure...
echo.

REM Start Firebase emulators in background
echo [1/3] Starting Firebase emulators...
start "Firebase Emulators" cmd /c "firebase emulators:start"

REM Wait for emulators to be ready (adjust time if needed)
echo [2/3] Waiting for emulators to initialize (15 seconds)...
timeout /t 15 /nobreak

REM Create folder structure using Firebase Storage REST API
echo [3/3] Creating folder structure in storage...
curl -X POST "http://localhost:5002/v0/b/revoland-viewstory.firebasestorage.app/o?name=Revoland/PropertyVideos/Original/.temp" -H "Content-Type: application/octet-stream" -d ""

echo.
echo ====================================
echo Setup complete!
echo ====================================
echo Firebase Emulators UI: http://localhost:5003
echo Storage Emulator: http://localhost:5002
echo Folder created: revoland-viewstory.firebasestorage.app/Revoland/PropertyVideos/Original
echo.
echo Press any key to open Emulator UI in browser...
pause > nul
start http://localhost:5003

