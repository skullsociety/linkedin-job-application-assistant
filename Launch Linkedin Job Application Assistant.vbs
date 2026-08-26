Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
folder = files.GetParentFolderName(WScript.ScriptFullName)
python = files.BuildPath(folder, ".venv\Scripts\pythonw.exe")
If Not files.FileExists(python) Then
  MsgBox "This project has not been set up yet. Run Setup Linkedin Job Assistant.bat first.", 48, "LinkedIn Job Application Assistant"
  WScript.Quit 1
End If
application = folder & "\Linkedin Job Application Assistant.pyw"
shell.Run Chr(34) & python & Chr(34) & " " & Chr(34) & application & Chr(34), 0, False
