@echo off
cd /d C:\Code\claude-deck
set PYTHONPATH=src
venv\Scripts\python.exe -m claude_deck.app
