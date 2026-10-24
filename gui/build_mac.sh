#!/bin/zsh
# 打 Mac 安装包：gui/dist/安卓去广告.app 和 .dmg
# 用法：gui/build_mac.sh            不签名（自己测）
#       SIGN_ID="Developer ID Application: 名字 (TEAMID)" NOTARY_PROFILE=钥匙串里的公证配置名 gui/build_mac.sh
set -e
cd "${0:A:h}/.."
PY=gui/.venv/bin/python
NAME="安卓去广告"
VER=$($PY -c "import re;print(re.search(r'VERSION = \"([^\"]+)\"', open('gui/app.py').read()).group(1))")
rm -rf gui/build gui/dist
$PY -m PyInstaller --noconfirm --windowed --name "$NAME" \
  --distpath gui/dist --workpath gui/build --specpath gui/build \
  --osx-bundle-identifier com.rddmwmddr.androidadcleaner \
  --icon "$PWD/gui/icon.icns" \
  --add-data "$PWD/tool:tool" --add-data "$PWD/recipes:recipes" \
  --add-data "$PWD/images:images" --add-data "$PWD/gui/web:gui/web" \
  --collect-all uiautomator2 --collect-all adbutils \
  --hidden-import uiautomator2 --hidden-import adbutils --hidden-import PIL \
  gui/app.py
APP="gui/dist/$NAME.app"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VER" "$APP/Contents/Info.plist"
if [ -n "$SIGN_ID" ]; then
  codesign --force --deep --options runtime --timestamp --sign "$SIGN_ID" "$APP"
  codesign --verify --deep --strict "$APP"
fi
DMG="gui/dist/$NAME-$VER-mac.dmg"
hdiutil create -volname "$NAME" -srcfolder "$APP" -ov -format UDZO "$DMG" >/dev/null
if [ -n "$SIGN_ID" ]; then
  codesign --force --timestamp --sign "$SIGN_ID" "$DMG"
fi
if [ -n "$NOTARY_PROFILE" ]; then
  xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait
  xcrun stapler staple "$DMG"
fi
echo "完成：$DMG"
