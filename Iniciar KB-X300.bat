@echo off
title KB-X300 App
cd /d "%~dp0"
python app.py
if errorlevel 1 pause
