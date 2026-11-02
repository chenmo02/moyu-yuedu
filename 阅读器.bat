@echo off
rem ============================================================
rem  后台起一个本地 https 服务，然后用浏览器打开
rem  地址形如 https://chat.deepseek6.com/a/chat/s/<会话id>
rem  首次启动会先走旧地址把书架迁移过来，之后直接开新地址
rem ============================================================
setlocal
set "PYW=%LOCALAPPDATA%\Python\bin\pythonw.exe"
if not exist "%PYW%" set "PYW=%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw"
start "" "%PYW%" "%~dp0server.py"
exit
