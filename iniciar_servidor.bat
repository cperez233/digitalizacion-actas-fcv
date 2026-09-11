@echo off
title Servidor Buscador de Actas FCV
echo ======================================================
echo    FUNDACION CARDIOVASCULAR DE COLOMBIA (FCV)
echo       Servidor Seguro - Buscador de Actas
echo ======================================================
echo.
echo Iniciando servidor en el puerto 8080...
echo Accede en tu navegador a: http://localhost:8080
echo.
echo Para detener el servidor, presiona Ctrl + C en esta ventana.
echo ======================================================
python server.py 8080
pause
