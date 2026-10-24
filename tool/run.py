#!/usr/bin/env python3
"""手机去广告 · 总入口。所有命令都要带 -s <序列号>（adb devices 第一列）。

  python3 tool/run.py devices                      列出连着的手机、型号、系统版本、有没有现成菜谱
  python3 tool/run.py -s 序列号 check              只读：锁屏、菜谱匹配、广告包挂起状态
  python3 tool/run.py -s 序列号 backup             改动前快照，存到 backups/<型号>-<时间>/
  python3 tool/run.py -s 序列号 recipe [段名 …]     跑本机型菜谱（不带段名=全跑）
  python3 tool/run.py -s 序列号 chan-scan          只读：列出开着的营销通知渠道 → backups/.../channels.tsv
  python3 tool/run.py -s 序列号 chan-off 清单.tsv   关掉清单里的渠道
  python3 tool/run.py -s 序列号 chan-on  清单.tsv   还原
  python3 tool/run.py -s 序列号 suspend 包名 …       挂起广告包（先征得机主同意），记录到 backups/.../suspended.txt
  python3 tool/run.py -s 序列号 unsuspend [包名 …]   解除挂起（不给包名=解除记录里的全部）
  python3 tool/run.py -s 序列号 finish             收尾：插电常亮改回备份时的值
"""
import datetime, glob, os, re, shutil, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "tool")
BACKUPS = os.path.join(ROOT, "backups")

# 各品牌常见的系统广告包。只在机主同意后挂起；挂起可一条命令还原。
AD_PKGS = {
    "OPPO": ["com.opos.ads", "com.heytap.pictorial", "com.nearme.instant.platform", "com.oppo.instant.local.service"],
    "OnePlus": ["com.opos.ads", "com.heytap.pictorial", "com.nearme.instant.platform", "com.oppo.instant.local.service"],
    "realme": ["com.opos.ads", "com.heytap.pictorial", "com.nearme.instant.platform", "com.oppo.instant.local.service"],
    "HONOR": ["com.hihonor.quickengine", "com.hihonor.quickgame", "com.honor.quickgamecenter"],
    "Xiaomi": ["com.miui.systemAdSolution"],
    "Redmi": ["com.miui.systemAdSolution"],
    "vivo": [],
}
# 挂了会坏功能的包，不许挂
NEVER = {"com.heytap.quicksearchbox", "com.coloros.assistantscreen", "com.android.systemui",
         "com.vivo.systemuiplugin", "com.heytap.market", "com.xiaomi.market", "com.hihonor.appmarket"}


def adb_bin():
    for c in (os.environ.get("ADB"), shutil.which("adb"),
              os.path.expanduser("~/Library/Android/sdk/platform-tools/adb"),
              os.path.expanduser("~/platform-tools/adb"), os.path.expanduser("~/android-tools/platform-tools/adb")):
        if c and os.path.exists(c):
            return c
    sys.exit("找不到 adb。安装方法见 docs/01-准备工作.md")


ADB = adb_bin()


def sh(serial, cmd, check=False):
    r = subprocess.run([ADB, "-s", serial, "shell", cmd], capture_output=True, text=True)
    return r.stdout.strip()


def prop(serial, k):
    return sh(serial, f"getprop {k}")


def info(serial):
    return {
        "brand": prop(serial, "ro.product.brand"),
        "model": prop(serial, "ro.product.model"),
        "name": prop(serial, "ro.vendor.oplus.market.name") or prop(serial, "ro.product.marketname") or prop(serial, "ro.product.vendor.marketname"),
        "build": prop(serial, "ro.build.display.id"),
        "android": prop(serial, "ro.build.version.release"),
    }


def recipe_for(model):
    hits = glob.glob(os.path.join(ROOT, "recipes", f"*-{model}", "recipe.py"))
    return hits[0] if hits else None


def locked(serial):
    return "isKeyguardShowing=true" in sh(serial, "dumpsys window | grep -m1 isKeyguardShowing") or \
           "mDreamingLockscreen=true" in sh(serial, "dumpsys window | grep -m1 mDreamingLockscreen")


def latest_backup(serial, create=False):
    m = info(serial)["model"]
    hits = sorted(glob.glob(os.path.join(BACKUPS, f"{m}-*")))
    if hits and not create:
        return hits[-1]
    d = os.path.join(BACKUPS, f"{m}-{datetime.datetime.now():%Y%m%d-%H%M}")
    os.makedirs(d, exist_ok=True)
    return d


def suspended(serial, pkg):
    out = sh(serial, f"dumpsys package {pkg} | grep -m1 -o 'suspended=[a-z]*'")
    return out.endswith("true")


def py(script, *args):
    return subprocess.call([sys.executable, os.path.join(TOOL, script), *args])


def main():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        print(__doc__); return
    if a[0] == "devices":
        out = subprocess.run([ADB, "devices"], capture_output=True, text=True).stdout
        rows = [l.split("\t") for l in out.splitlines()[1:] if "\t" in l]
        if not rows:
            print("没有连着的手机。检查数据线、USB 调试，见 docs/01-准备工作.md")
        for ser, st in rows:
            if st != "device":
                print(f"{ser}\t{st}\t（unauthorized=手机上点「允许 USB 调试」；offline=重插或重开无线调试）"); continue
            i = info(ser); r = recipe_for(i["model"])
            print(f"{ser}\t{i['name'] or i['brand']+' '+i['model']}\t{i['model']}\t{i['build']}\t菜谱：{os.path.relpath(r, ROOT) if r else '无（只能跑通用部分）'}")
        return
    if a[0] != "-s" or len(a) < 3:
        sys.exit("命令格式：run.py -s <序列号> <命令>。先跑 run.py devices 看序列号")
    s, cmd, rest = a[1], a[2], a[3:]

    if cmd == "check":
        i = info(s); r = recipe_for(i["model"])
        print(f"机型：{i['name'] if i['name'].upper().startswith(i['brand'].upper()) else i['brand']+' '+i['name']}（{i['model']}），系统 {i['build']}，Android {i['android']}")
        print(f"锁屏：{'是（请机主解锁）' if locked(s) else '否'}")
        if r:
            src = open(r, encoding="utf-8").read()
            m = re.search(r'^BUILD\s*=\s*"([^"]*)"', src, re.M)
            ok = (not m) or i["build"].startswith(m.group(1))
            print(f"菜谱：{os.path.relpath(r, ROOT)}；录制版本 {m.group(1) if m else '未标'}，{'版本一致' if ok else '版本不同，部分步骤可能找不到入口'}")
        else:
            print("菜谱：没有。可跑：通知渠道 chan-scan/chan-off、广告包挂起；其余照 docs/清单 手动做，或用 tool/explore.py 探路")
        for p in AD_PKGS.get(i["brand"], []):
            exists = "package:" in sh(s, f"pm path {p}")
            print(f"  广告包 {p}：{'未安装' if not exists else ('已挂起' if suspended(s, p) else '未挂起')}")
        print(f"插电常亮：{sh(s, 'settings get global stay_on_while_plugged_in')}")

    elif cmd == "backup":
        d = latest_backup(s, create=True)
        open(os.path.join(d, "info.txt"), "w").write("\n".join(f"{k}={v}" for k, v in info(s).items()))
        for name, c in [("sys.txt", "pm list packages -s"), ("user.txt", "pm list packages -3"),
                        ("disabled.txt", "pm list packages -d"), ("notif.txt", "dumpsys notification --noredact")]:
            open(os.path.join(d, name), "w").write(sh(s, c))
        st = "\n".join(f"## {n}\n" + sh(s, f"settings list {n}") for n in ("system", "secure", "global"))
        open(os.path.join(d, "settings-before.txt"), "w").write(st)
        open(os.path.join(d, "stay_on.txt"), "w").write(sh(s, "settings get global stay_on_while_plugged_in"))
        print(f"快照已存：{os.path.relpath(d, ROOT)}")

    elif cmd == "recipe":
        r = recipe_for(info(s)["model"])
        if not r:
            sys.exit("这个型号没有菜谱。见 docs/04-给新机型做菜谱.md")
        if locked(s):
            sys.exit("手机锁屏了，请机主解锁后再跑")
        sh(s, "settings put global stay_on_while_plugged_in 7")
        sys.exit(py("fast.py", "-s", s, "run", r, *rest))

    elif cmd == "chan-scan":
        d = latest_backup(s)
        out = subprocess.run([sys.executable, os.path.join(TOOL, "chan_fast.py"), "-s", s, "scan"],
                             capture_output=True, text=True).stdout
        f = os.path.join(d, "channels.tsv")
        open(f, "w", encoding="utf-8").write(
            "# 包名\t渠道id\t渠道名。人工核对：删掉服务类（热点共享、红包、防盗、直播提醒等）后再 chan-off\n" + out)
        print(out); print(f"候选清单：{os.path.relpath(f, ROOT)}（共 {out.count(chr(10))} 条）")

    elif cmd in ("chan-off", "chan-on"):
        if not rest:
            sys.exit("要给清单文件，比如 backups/<型号>-<时间>/channels.tsv")
        sys.exit(py("chan_fast.py", "-s", s, cmd.split("-")[1], rest[0]))

    elif cmd == "suspend":
        bad = [p for p in rest if p in NEVER]
        if bad:
            sys.exit(f"这些包挂了会坏功能，不挂：{bad}")
        d = latest_backup(s)
        with open(os.path.join(d, "suspended.txt"), "a") as f:
            for p in rest:
                print(p, sh(s, f"pm suspend --user 0 {p}").splitlines()[-1:] or "")
                if suspended(s, p):
                    f.write(p + "\n")

    elif cmd == "unsuspend":
        pk = rest
        if not pk:
            f = os.path.join(latest_backup(s), "suspended.txt")
            pk = sorted(set(open(f).read().split())) if os.path.exists(f) else []
        for p in pk:
            sh(s, f"pm unsuspend --user 0 {p}")
            print(p, "已挂起" if suspended(s, p) else "已恢复")

    elif cmd == "finish":
        f = os.path.join(latest_backup(s), "stay_on.txt")
        v = open(f).read().strip() if os.path.exists(f) else "0"
        sh(s, f"settings put global stay_on_while_plugged_in {v or 0}")
        sh(s, "input keyevent HOME")
        print(f"插电常亮已改回 {v or 0}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
