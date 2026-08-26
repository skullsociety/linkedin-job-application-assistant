Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")

folder = files.GetParentFolderName(WScript.ScriptFullName)
python = files.BuildPath(folder, ".venv\Scripts\pythonw.exe")
If Not files.FileExists(python) Then
  MsgBox "This project has not been set up yet. Run Setup Linkedin Job Assistant.bat first.", 48, "LinkedIn Job Application Assistant"
  WScript.Quit 1
End If
command = Chr(34) & python & Chr(34) & " -m companion.server"

shell.CurrentDirectory = folder
shell.Run command, 0, False
WScript.Sleep 1500
shell.Run "http://127.0.0.1:8766/", 1, False
