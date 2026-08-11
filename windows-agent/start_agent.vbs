Option Explicit

' Lanzador silencioso para el Programador de tareas de Windows.
' El .bat se conserva como lanzador manual/de depuracion y muestra la consola.

Dim shell
Dim fileSystem
Dim agentDirectory
Dim command

Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")

agentDirectory = fileSystem.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = agentDirectory

command = "py.exe """ & agentDirectory & "\main.py"""
shell.Run command, 0, False
