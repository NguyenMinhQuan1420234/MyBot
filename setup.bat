@echo off
REM MyBot Installation Script for Windows
REM This script creates a virtual environment and installs all dependencies

setlocal enabledelayedexpansion

echo.
echo ========================================
echo    MyBot - Auto Setup Script
echo ========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.10+ from https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [1/3] Creating virtual environment...
if exist .venv (
    echo Virtual environment already exists, skipping creation.
) else (
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment
        pause
        exit /b 1
    )
    echo Virtual environment created successfully!
)

echo.
echo [2/3] Activating virtual environment...
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo ERROR: Failed to activate virtual environment
    pause
    exit /b 1
)
echo Virtual environment activated!

echo.
echo [3/3] Installing dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)
echo Dependencies installed successfully!

echo.
echo ========================================
echo    Setup Complete!
echo ========================================
echo.
echo Next steps:
echo 1. Create BOT_TOKEN.env with your tokens:
echo    TELE_BOT_TOKEN=your_telegram_bot_token
echo    GEMINI_API_KEY=your_gemini_api_key
echo.
echo 2. Run the bot:
echo    python BOT.py
echo.
pause
