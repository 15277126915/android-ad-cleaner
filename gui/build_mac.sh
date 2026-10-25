#!/bin/zsh
# 打 Mac 安装包
#   gui/build_mac.sh                      Apple 芯片版，不签名（自己测）
#   ARCH=x86_64 gui/build_mac.sh          Intel 版（在 Apple 芯片的 Mac 上要装 Rosetta）
#   SIGN_ID="Developer ID Application: 名字 (TEAMID)" NOTARY_PROFILE=钥匙串公证配置名 gui/build_mac.sh
# 产物：gui/dist/<架构>/安卓去广告.app、gui/dist/AndroidAdCleaner-<版本>-mac-<arm64|intel>.dmg
set -eo pipefail
cd "${0:A:h}/.."
ARCH=${ARCH:-arm64}
NAME="安卓去广告"
if [ "$ARCH" = "x86_64" ]; then
  VENV=gui/.venv-x86; RUN=(arch -x86_64); TAG=intel; PYVER=cpython-3.12-macos-x86_64
else
  VENV=gui/.venv; RUN=(); TAG=arm64; PYVER=cpython-3.12-macos-aarch64
fi
if [ ! -x $VENV/bin/python ]; then
  uv venv --python $PYVER $VENV
  uv pip install --python $VENV/bin/python pywebview pyinstaller uiautomator2 pillow
fi
PY=$VENV/bin/python
VER=$($PY -c "import re;print(re.search(r'VERSION = \"([^\"]+)\"', open('gui/app.py', encoding='utf-8').read()).group(1))")
OUT=gui/dist/$ARCH
rm -rf gui/build/$ARCH $OUT; mkdir -p gui/build
DATA="$PWD/gui/build/$ARCH/data"
$PY gui/bundle_data.py "$DATA"
$RUN $PY -m PyInstaller --noconfirm --windowed --name "$NAME" \
  --distpath $OUT --workpath gui/build/$ARCH --specpath gui/build/$ARCH \
  --osx-bundle-identifier com.rddmwmddr.androidadcleaner \
  --icon "$PWD/gui/icon.icns" \
  --add-data "$DATA/tool:tool" --add-data "$DATA/recipes:recipes" \
  --add-data "$DATA/images:images" --add-data "$DATA/gui/web:gui/web" \
  --collect-all uiautomator2 --collect-all adbutils \
  --hidden-import uiautomator2 --hidden-import adbutils --hidden-import PIL \
  gui/app.py >/dev/null 2>gui/build/pyinstaller-$ARCH.log
APP="$OUT/$NAME.app"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VER" "$APP/Contents/Info.plist"
echo "架构：$(file "$APP/Contents/MacOS/$NAME" | sed 's/.*: //')"

if [ -n "$SIGN_ID" ]; then
  codesign --force --deep --options runtime --timestamp --sign "$SIGN_ID" "$APP"
  codesign --verify --deep --strict "$APP"
  if [ -n "$NOTARY_PROFILE" ]; then          # App 本身先公证并钉上凭证：用户离线打开也能通过检查
    ZIP="gui/build/$ARCH/app.zip"
    ditto -c -k --keepParent "$APP" "$ZIP"
    xcrun notarytool submit "$ZIP" --keychain-profile "$NOTARY_PROFILE" --wait | grep -E "status:|id:" | tail -2
    xcrun stapler staple "$APP" | tail -1
  fi
fi

DMG="gui/dist/AndroidAdCleaner-$VER-mac-$TAG.dmg"
rm -f "$DMG"
STAGE="gui/build/$ARCH/dmg"; rm -rf "$STAGE"; mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"; ln -s /Applications "$STAGE/应用程序"
hdiutil create -volname "$NAME" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null 2>&1
if [ -n "$SIGN_ID" ]; then
  codesign --force --timestamp --sign "$SIGN_ID" "$DMG"
  if [ -n "$NOTARY_PROFILE" ]; then
    xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait | grep -E "status:" | tail -1
    xcrun stapler staple "$DMG" | tail -1
  fi
fi
echo "完成：$DMG（$(du -h "$DMG" | cut -f1)）"
