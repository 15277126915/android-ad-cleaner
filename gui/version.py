"""打印 gui/app.py 里的版本号（给打包脚本用）。"""
import os, re
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py"), encoding="utf-8").read()
print(re.search(r'VERSION = "([^"]+)"', src).group(1))
