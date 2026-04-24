@echo off
powershell -ExecutionPolicy Bypass -File "%~dp0docker-core-acceptance.ps1" %*
