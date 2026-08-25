@echo off
chcp 65001 >nul
echo ============================================================
echo  RimeTool · 打包为 exe（onedir：RimeTool.exe + _internal\）
echo  本脚本须在【普通 Windows 终端】运行（双击即可；不要通过
echo  WorkBuddy / 其他带沙箱限制的终端，否则构建可能因安全删除
echo  钩子失败）。请先确认已安装 Python 3.11 + PyQt5 + jieba。
echo ============================================================
cd /d "D:\Program Files\Rime\RimeTool"

REM 输出目录：D:\Documents\Downloads\Temp\RimeTool\RimeTool\RimeTool.exe
"D:\Program Files\Python\Python311\python.exe" -m PyInstaller ^
  --noconsole --onedir --name RimeTool ^
  --add-data "D:\Program Files\Rime\RimeTool\resources;resources" ^
  --paths "D:\Program Files\Rime\RimeTool" ^
  --hidden-import jieba ^
  --distpath "D:\Documents\Downloads\Temp\RimeTool" ^
  --workpath "D:\Documents\Downloads\Temp\RimeTool\_build" ^
  --specpath "D:\Documents\Downloads\Temp\RimeTool\_build" ^
  main.py

echo.
echo 构建结束。若成功，exe 位于：
echo   D:\Documents\Downloads\Temp\RimeTool\RimeTool\RimeTool.exe
echo （首次使用：双击 RimeTool.exe → 点「配置」设置 tsv_path 与
echo  rime_config_dir → 保存，之后即可使用。）
pause
