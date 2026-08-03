@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

:: ============================================================
::  Amlogic USB Burning Tool 魔改启动器
::  兼容国产 eMMC (Foresee/Biwin/YTXC, mafId=0xD6)
::
::  功能:
::    1. 自动搜索 USB Burning Tool 安装路径
::    2. 备份并补丁 UsbRomDrv.dll (延长超时)
::    3. 导入注册表设置 (禁用 erase_bootloader)
::    4. 启动 USB Burning Tool
:: ============================================================

title Amlogic USB Burning Tool 魔改版 — 国产 eMMC 兼容

echo ============================================================
echo   Amlogic USB Burning Tool 魔改启动器
echo   兼容国产 eMMC (Foresee/Biwin/YTXC, mafId=0xD6)
echo ============================================================
echo.

:: ---- 搜索 USB Burning Tool ----
set "TOOL_DIR="
for %%P in (
    "C:\Program Files (x86)\Amlogic\USB_Burning_Tool"
    "C:\Program Files\Amlogic\USB_Burning_Tool"
    "C:\Program Files (x86)\AML\USB_Burning_Tool"
    "%~dp0"
    "%CD%"
) do (
    if exist "%%~P\AML_Burn_Tool.exe" (
        set "TOOL_DIR=%%~P"
        goto :found
    )
)

echo [!] 未找到 Amlogic USB Burning Tool
echo [!] 请将本脚本放在 USB Burning Tool 目录下运行
echo [!] 或安装 Amlogic USB Burning Tool v2.1.6+
echo.
pause
exit /b 1

:found
echo [+] 找到工具: %TOOL_DIR%
echo.

:: ---- 补丁 UsbRomDrv.dll ----
set "DLL_PATH=%TOOL_DIR%\UsbRomDrv.dll"
if exist "%DLL_PATH%" (
    echo [*] 补丁 UsbRomDrv.dll (延长超时)...
    python "%~dp0patch_dll.py" "%DLL_PATH%" 2>nul
    if !errorlevel! neq 0 (
        echo [=] DLL 补丁跳过 (可能已补丁或版本不同)
    )
) else (
    echo [=] UsbRomDrv.dll 不存在, 跳过 DLL 补丁
)
echo.

:: ---- 导入注册表设置 ----
echo [*] 导入注册表设置 (禁用 erase_bootloader)...
regedit /s "%~dp0patches\burning_tool_settings.reg" 2>nul
if !errorlevel! equ 0 (
    echo [+] 注册表设置已导入
) else (
    echo [=] 注册表导入跳过 (需要管理员权限)
)
echo.

:: ---- 复制补丁配置 ----
if exist "%~dp0patches\aml_sdc_burn.ini" (
    echo [*] 复制补丁配置文件...
    copy /y "%~dp0patches\aml_sdc_burn.ini" "%TOOL_DIR%\" >nul 2>&1
    copy /y "%~dp0patches\platform.conf" "%TOOL_DIR%\" >nul 2>&1
    echo [+] 配置文件已复制
    echo.
)

:: ---- 启动 USB Burning Tool ----
echo ============================================================
echo   准备就绪! 启动 USB Burning Tool...
echo.
echo   注意:
echo   1. 在 GUI 中取消勾选 "Erase bootloader"
echo   2. 勾选 "Erase flash" 和 "Verify flash"
echo   3. 不勾选 "Preserve user data"
echo   4. 导入 .img 文件, 点 Start
echo ============================================================
echo.

start "" "%TOOL_DIR%\AML_Burn_Tool.exe"

timeout /t 3 >nul
