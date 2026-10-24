# Windows 打包：一次分析，两个 exe 共用 _internal
#   AndroidAdCleaner.exe  窗口程序（用户双击）
#   aac-cli.exe           命令行程序（客户端在后台调用，有正常的标准输出）
# 用法（仓库根目录）：pyinstaller --noconfirm --distpath gui/dist --workpath gui/build gui/windows.spec
import os
from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
datas = [(os.path.join(ROOT, d), d) for d in ("tool", "recipes", "images")] + [(os.path.join(ROOT, "gui", "web"), "gui/web")]
binaries, hidden = [], ["uiautomator2", "adbutils", "PIL"]
for pkg in ("uiautomator2", "adbutils", "webview"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hidden += h

a = Analysis([os.path.join(ROOT, "gui", "app.py")], pathex=[ROOT], binaries=binaries, datas=datas, hiddenimports=hidden)
pyz = PYZ(a.pure)
icon = os.path.join(ROOT, "gui", "icon.ico")
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name="AndroidAdCleaner", console=False, icon=icon)
cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name="aac-cli", console=True, icon=icon)
coll = COLLECT(gui, cli, a.binaries, a.datas, name="AndroidAdCleaner")
