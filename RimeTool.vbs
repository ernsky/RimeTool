Set ws = CreateObject("WScript.Shell")
pyw = "D:\Program Files\Python\Python311\pythonw.exe"
script = "D:\Program Files\Rime\RimeTool\main.py"
cmd = Chr(34) & pyw & Chr(34) & " " & Chr(34) & script & Chr(34)
ws.Run cmd, 1, False
