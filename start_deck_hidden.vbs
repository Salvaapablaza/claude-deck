' Launch the claude-deck daemon without a console window (for shell:startup)
Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = "C:\Code\claude-deck"
shell.Environment("PROCESS")("PYTHONPATH") = "src"
shell.Run """C:\Code\claude-deck\venv\Scripts\pythonw.exe"" -m claude_deck.app", 0, False
