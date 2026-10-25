#!/usr/bin/env python3
"""去广告快速引擎（uiautomator2，读屏 ~0.03 秒）。

命令行：
  fast.py -s SERIAL ls                 列当前屏：文字 + 开关状态
  fast.py -s SERIAL tap 文字 [文字…]    依次点（找不到会往下翻着找）
  fast.py -s SERIAL off [保留词,…]      当前列表里开着的开关全关（保留词命中的不动），一路翻到底
  fast.py -s SERIAL scan                 只读：翻到底列出所有开关
  fast.py -s SERIAL only 词,词…         只关标题含这些词的开关
  fast.py -s SERIAL run 机型脚本.py         跑一个品牌机型脚本
在脚本里：from fast import Phone
"""
import os, re, sys, time, xml.etree.ElementTree as ET
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(encoding="utf-8", errors="replace")   # Windows 控制台默认不是 UTF-8
    except Exception:
        pass
import uiautomator2 as u2

BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
DISMISS = ("以后再说", "暂不更新", "暂不", "取消", "我知道了", "跳过", "禁止", "不再提示")
CONFIRM = ("确定", "关闭", "仍要关闭", "确认关闭", "确认", "继续关闭", "关闭推荐", "仍然关闭")


def bounds(n):
    m = BOUNDS.match(n.get("bounds", ""))
    return tuple(map(int, m.groups())) if m else (0, 0, 0, 0)


# 「防止/限制/阻止广告跟踪」「关闭个性化推荐」这类开关是反着的：打开才是保护。不能当广告开关关掉。
NEG_PREFIX = re.compile(r"^(防止|限制|阻止|禁止|拒绝|不允许|屏蔽|关闭|停用|不接收|不显示|不推送|停止)")
AD_WORDS = re.compile(r"广告|跟踪|追踪|推荐|个性化|营销|资讯|热搜|热点|定向|画像")   # 不含「推送」：「关闭推送」会连订单通知一起关
TRACK_WORDS = re.compile(r"广告|跟踪|追踪")


def want_state(title):
    """这个开关该处在什么状态：False=关（普通广告开关）；True=开（保护类开关）；None=不碰。"""
    if NEG_PREFIX.search(title or ""):
        return True if AD_WORDS.search(title) else None
    return False


class Phone:
    def __init__(self, serial, log=True):
        self.d = u2.connect(serial)
        self.d.settings["operation_delay"] = (0, 0)
        self.W, self.H = self.d.window_size()
        self.log = log
        self.changed = []          # (页面, 标题) 记录本次关掉的
        self.miss = 0              # 本段已经没找到几次；>0 说明路径对不上，后面只看当前屏、不再翻页找

    def say(self, *a):
        if self.log:
            print(*a, flush=True)

    # ---------- 读屏 ----------
    def tree(self):
        return ET.fromstring(self.d.dump_hierarchy())

    def focus(self):
        """当前焦点窗口（~0.1 秒；u2 的 app_current 在浮窗上会卡 10 秒）。"""
        out = self.d.shell("dumpsys window | grep -m1 mCurrentFocus").output
        m = re.search(r"u0 (\S+)}", out)
        if m:
            return m.group(1)
        out = self.d.shell("dumpsys activity activities | grep -m1 topResumedActivity").output
        m = re.search(r" (\S+/\S+)", out)
        return m.group(1) if m else ""

    def texts(self, root=None):
        root = root if root is not None else self.tree()
        out = []
        for n in root.iter("node"):
            if n.get("package") == "com.android.systemui" and not getattr(self, "sysui", False):
                continue                      # 状态栏/通知栏文字不算
            t = (n.get("text") or n.get("content-desc") or "").strip()
            if t and self.on_screen(n):
                out.append((t, bounds(n), n))
        return out

    def on_screen(self, n):
        """折叠屏合上时，dump 里还留着内屏那份节点，坐标在外屏之外（Issue #2）；点上去没反应。"""
        if n.get("visible-to-user") == "false":
            return False
        l, t, r, b = bounds(n)
        cx, cy = (l + r) // 2, (t + b) // 2
        return 0 <= cx < self.W and 0 <= cy < self.H

    def switches(self, root=None):
        """[(标题, checked, (cx,cy))]，标题取开关所在行的第一段文字。"""
        root = root if root is not None else self.tree()
        parent = {c: p for p in root.iter() for c in p}
        out = []
        shot = None
        for n in root.iter("node"):
            if n.get("checkable") != "true":
                rid = (n.get("resource-id") or "").lower()
                if "switch" in rid and n.get("clickable") == "true":      # 自绘开关：看颜色
                    l, t, r, b = bounds(n)
                    if r - l > 0 and b - t > 0:
                        if shot is None:
                            shot = self.d.screenshot()
                        on = self._pixel_on(shot, l, t, r, b)
                        n.set("checked", "true" if on else "false")
                        n.set("checkable", "true")
                        n.set("class", "SelfDrawnSwitch")
                if n.get("checkable") != "true":
                    continue
            cls = n.get("class", "")
            if not any(k in cls for k in ("Switch", "CheckBox", "ToggleButton", "Compound")) and n.get("clickable") != "true":
                continue
            l, t, r, b = bounds(n)
            if r - l <= 0 or b - t <= 0 or not self.on_screen(n):
                continue
            cy = (t + b) // 2
            title, p = "", n
            for _ in range(5):
                p = parent.get(p)
                if p is None:
                    break
                cand = []
                for x in p.iter("node"):
                    tx = (x.get("text") or "").strip()
                    if x is n or not tx or tx in ("开", "关", "已开启", "已关闭", "开启", "关闭"):
                        continue
                    xl, xt, xr, xb = bounds(x)
                    if xb <= xt:
                        continue
                    # 标题要和开关在同一行：取竖直方向离开关中心最近的那段文字（Issue #2：
                    # 父容器里第一段文字可能是上一行的标题，会把「自动更新」认成「每次联网时通知」）
                    dist = 0 if xt <= cy <= xb else min(abs(xt - cy), abs(xb - cy))
                    cand.append((dist, xt, tx))
                if cand:
                    cand.sort()
                    if cand[0][0] <= max(60, (b - t)):
                        title = cand[0][2]
                        break
            out.append((title, n.get("checked") == "true", ((l + r) // 2, cy)))
        # 同一行有「整行」和「开关」两个 checkable 时，留最靠右的那个
        rows = []
        for sw in sorted(out, key=lambda s: s[2][1]):
            if rows and abs(rows[-1][2][1] - sw[2][1]) < 30:
                if sw[2][0] > rows[-1][2][0]:
                    rows[-1] = sw if sw[0] else (rows[-1][0], sw[1], sw[2])
            else:
                rows.append(sw)
        return rows

    def locked(self):
        out = self.d.shell("dumpsys window | grep -m1 isKeyguardShowing").output
        return "true" in out

    def sig(self):
        return "|".join(t for t, _, _ in self.texts())

    def scroll_more(self):
        """翻一页；翻完没出现新文字（到底、回弹）返回 False。"""
        before = {t for t, _, _ in self.texts()}
        self.scroll()
        after = {t for t, _, _ in self.texts()}
        return not after <= before

    @staticmethod
    def _pixel_on(img, l, t, r, b):
        """开关轨道取几个点：彩色（蓝/绿/橙，饱和度高）=开，灰白=关。"""
        img = img.convert("RGB")
        sat = 0
        for fx in (0.25, 0.5, 0.75):
            R, G, B = img.getpixel((int(l + (r - l) * fx), (t + b) // 2))
            sat = max(sat, max(R, G, B) - min(R, G, B))
        return sat > 60

    def ls(self):
        root = self.tree()
        print("·", self.focus())
        print(" / ".join(t for t, _, _ in self.texts(root)))
        for t, c, xy in self.switches(root):
            print(f"  [{'开' if c else '关'}] {t}  @{xy}")

    # ---------- 动作 ----------
    def click(self, x, y):
        self.d.shell(f"input swipe {x} {y} {x} {y} 80")   # 有的 App 吞 input tap

    def scroll(self, frac=0.45, up=False):
        """按下-移动-停 0.12 秒-松开：没有惯性，翻多少是多少，约 0.45 秒。"""
        x = self.W * 7 // 10 if self.W > 2000 else self.W // 2
        frac = min(frac, 0.58)                   # 留在 0.22H~0.80H 之间拖，避开标题栏和底栏
        y1, y2 = int(self.H * 0.80), int(self.H * (0.80 - frac))
        if up:
            y1, y2 = y2, y1
        c = [f"input motionevent DOWN {x} {y1}"]
        c += [f"input motionevent MOVE {x} {int(y1 + (y2 - y1) * i / 6)}" for i in range(1, 7)]
        c += ["sleep 0.12", f"input motionevent UP {x} {y2}"]
        self.d.shell(";".join(c))
        time.sleep(0.15)

    def top(self, n=4):
        for _ in range(n):
            before = {t for t, _, _ in self.texts()}
            self.scroll(0.58, up=True)
            if {t for t, _, _ in self.texts()} <= before:
                break

    def find(self, text, exact=False, root=None, edge_ok=False):
        for t, (l, tp, r, b), n in self.texts(root):
            if (t == text) if exact else (text in t):
                if b <= tp or r <= l:
                    continue
                cy = (tp + b) // 2
                if cy < self.H * 0.92:
                    return ((l + r) // 2, cy)
                if edge_ok == "tab":                     # 底部标签栏：直接点中心
                    return ((l + r) // 2, cy)
                if edge_ok and tp < self.H * 0.975:      # 已到页底翻不上来：点这一行的上沿
                    return ((l + r) // 2, tp + 15)
        return None

    CLOSE = re.compile(r"close|关闭|跳过|skip|cancel|dismiss|iv_x\b|btn_x\b", re.I)

    def dismiss(self):
        """挡路的更新/推荐/权限弹窗：点拒绝类按钮（不替用户同意任何东西）。
        纯图片的广告弹窗没有文字，只有一个 ✕ 图标：找 desc/id 里带 close 的可点元素。"""
        root = self.tree()
        for n in root.iter("node"):
            if n.get("clickable") != "true" or n.get("package") == "com.android.systemui":
                continue
            key = (n.get("content-desc") or "") + " " + (n.get("resource-id") or "")
            if self.CLOSE.search(key) and not (n.get("text") or "").strip():
                l, t, r, b = bounds(n)
                if 0 < r - l < self.W * 0.3 and 0 < b - t < self.H * 0.12:   # 小图标，不是整行
                    self.click((l + r) // 2, (t + b) // 2); time.sleep(0.6)
                    self.say(f"  · 弹窗点了 ✕（{key.strip()[:40]}）")
                    return "✕"
        tx = self.texts(root)
        if len(tx) > 16:
            return None
        for w in DISMISS:
            for t, (l, tp, r, b), _ in tx:
                if t == w:
                    self.click((l + r) // 2, (tp + b) // 2); time.sleep(0.6)
                    self.say(f"  · 弹窗点了「{w}」")
                    return w
        return None

    def tap(self, text, exact=False, scrolls=6, wait=0.6):
        """找到就点。往下翻着找；翻到底没有，就回顶部再找一遍。
        scrolls=0（点底栏/按钮）：不翻页，但 3 秒内边等边关弹窗。"""
        if scrolls == 0:
            t0 = time.time()
            while time.time() - t0 < 3.0:
                xy = self.find(text, exact, edge_ok="tab")
                if xy:
                    b = self.sig(); self.click(*xy); self.settle(b, wait + 0.4)
                    return True
                self.dismiss() or time.sleep(0.2)
            self.say(f"  ✗ 没找到「{text}」")
            return False
        if self.miss:                                   # 本段已经走丢：只看当前这一屏
            xy = self.find(text, exact)
            if xy:
                b = self.sig(); self.click(*xy); self.settle(b, wait + 0.4)
                self.miss = 0
                return True
            self.miss += 1
            self.say(f"  ✗ 没找到「{text}」（快速放弃）")
            return False
        for rnd in range(2 if scrolls else 1):
            for i in range(scrolls + 1):
                edge = "tab" if scrolls == 0 else False
                xy = self.find(text, exact, edge_ok=edge)
                if not xy and self.dismiss():
                    xy = self.find(text, exact, edge_ok=edge)
                if xy:
                    b = self.sig(); self.click(*xy); self.settle(b, wait + 0.4)
                    return True
                if i < scrolls and not self.scroll_more():
                    xy = self.find(text, exact, edge_ok=True)
                    if xy:
                        self.click(*xy); time.sleep(wait)
                        return True
                    break
            if rnd == 0 and scrolls:
                self.top(scrolls + 2)
        self.miss += 1
        self.say(f"  ✗ 没找到「{text}」")
        return False

    def go(self, text, expect, tries=3, exact=True):
        """点 text，直到 expect 出现在屏幕上（被弹窗吞掉就再点）。"""
        for _ in range(tries):
            self.tap(text, exact=exact, scrolls=0)
            for _ in range(5):
                if self.find(expect) or self.find(expect, edge_ok="tab"):
                    return True
                self.dismiss() or time.sleep(0.3)
        self.say(f"  ✗ 点「{text}」后没出现「{expect}」")
        return False

    def settle(self, before, maxwait=0.8):
        """点完以后：画面一变（再稳 0.1 秒）就返回；最多等 maxwait。"""
        t0 = time.time()
        while time.time() - t0 < maxwait:
            time.sleep(0.1)
            cur = self.sig()
            if cur != before:
                time.sleep(0.1)
                return True
        return False

    def back(self, n=1):
        for _ in range(n):
            b = self.sig()
            self.d.shell("input keyevent BACK")
            self.settle(b, 0.6)

    def confirm(self):
        """开关后弹确认框就点确认类按钮。只认真按钮（Button 类），
        ColorOS 开关旁边的「开启/关闭」状态文字不算——点了会把开关又拨回去。"""
        time.sleep(0.2)
        root = self.tree()
        for c in CONFIRM:
            for n in root.iter("node"):
                if (n.get("text") or "").strip() == c and "Button" in (n.get("class") or ""):
                    l, t, r, b = bounds(n)
                    if r > l and b > t:
                        self.click((l + r) // 2, (t + b) // 2)
                        time.sleep(0.3)
                        return c
        return None

    def off(self, keep=(), only=None, page="", max_screens=40):
        """当前列表：关掉开着的开关。keep=标题含这些词的不动；only=只关含这些词的。
        每屏第一下单独点、看有没有弹窗/跳页；没有就把这一屏剩下的连着点完，最后统一核对。"""
        for _ in range(2 if self.miss else 10):  # 页面刚打开还没画完：等开关出现，最多 2 秒（本段已走丢就不等）
            if self.switches():
                break
            time.sleep(0.2)
        start = self.focus()
        done, slow = 0, False
        for _ in range(max_screens):
            root = self.tree()
            targets = []
            for t, c, xy in self.switches(root):
                if not t:
                    continue
                want = want_state(t)
                if want is None or c == want:            # 不碰的，或已经是目标状态
                    continue
                if any(k in t for k in keep):
                    continue
                if only is not None and not any(k in t for k in only) and not (want and TRACK_WORDS.search(t)):
                    continue                              # 「限制广告跟踪」这类保护开关：不在名单里也要打开
                if os.environ.get("AAC_REF") and only is None and not want:
                    continue                              # 参考脚本（同品牌别的机型录的）：不做整页全关
                if xy[1] < self.H * 0.08 or xy[1] > self.H * 0.985:
                    continue
                targets.append((t, xy, want))
            for i, (t, xy, _) in enumerate(targets):
                self.click(*xy)
                if i == 0 or slow:
                    if self.confirm():
                        slow = True                     # 这页会弹确认框，逐个点
                    elif self.focus() != start:
                        self.say(f"  ! 页面变了（{self.focus()}），停")
                        self.back()
                        return done
                else:
                    time.sleep(0.06)
            if targets:
                time.sleep(0.25)
                self.confirm()

                def wrong():                            # 还没到目标状态的标题
                    now = {t: c for t, c, _ in self.switches()}
                    return {t for t, _, w in targets if now.get(t, w) != w}
                still = wrong()
                for t, xy, _ in targets:
                    if t in still:                      # 没点动的补一次
                        self.click(*xy); self.confirm()
                still = wrong()
                if still:                               # 还有没拨过去的：等动画结束再点一次
                    time.sleep(0.8)
                    for t, xy, _ in targets:
                        if t in still:
                            self.click(*xy); self.confirm()
                    time.sleep(0.4)
                    still = wrong()
                for t, _, w in targets:
                    if t in still:
                        self.say(f"  ✗ {'打不开' if w else '关不掉'} {t}")
                    else:
                        self.say(f"  {'开（保护类开关）' if w else '关'} {t}")
                        self.changed.append((page, t))
                        done += 1
            if not self.scroll_more():
                break
        return done

    def focused_text(self):
        for n in self.tree().iter("node"):
            if n.get("focused") == "true" and "EditText" in (n.get("class") or ""):
                return n.get("text") or ""
        return None

    def type_text(self, kw, timeout=4.0):
        """往当前输入框打字。部分机型（小米 HyperOS 设置搜索）用 setText 会卡住、一直打「%」：
        加超时，打完核对；不对就清掉、改用剪贴板粘贴；还不对就关掉键盘返回 False，不卡住。"""
        import threading
        def attempt(fn):
            box = {}
            t = threading.Thread(target=lambda: box.setdefault("r", fn()), daemon=True)
            t.start(); t.join(timeout)
            if t.is_alive():
                self.d.shell("input keyevent BACK")          # 收起键盘，打断输入
                return False
            time.sleep(0.4)
            return (self.focused_text() or "").strip() == kw
        def clear():
            try:
                self.d.shell("input keyevent KEYCODE_MOVE_END")
                self.d.shell("input keyevent " + " ".join(["KEYCODE_DEL"] * 40))
            except Exception:
                pass
        def set_text():
            for sel in (dict(className="android.widget.EditText", focused=True), dict(className="android.widget.EditText")):
                el = self.d(**sel)
                if el.exists:                  # 别用 d(focused=True)：键盘窗口也有 focused 节点，会打到键盘上
                    return el.set_text(kw)
            return self.d(focused=True).set_text(kw)
        if attempt(set_text):
            return True
        clear()
        def paste():
            self.d.set_clipboard(kw)
            self.d.shell("input keyevent KEYCODE_PASTE")
        if attempt(paste):
            return True
        clear()
        self.d.shell("input keyevent BACK")
        return False

    def setting(self, kw, entry=None, box="搜索设置项"):
        """系统设置里搜 kw，点结果 entry（默认就是 kw）。"""
        self.miss = 0
        self.d.shell("am start -f 0x10008000 -a android.settings.SETTINGS")
        t0 = time.time()
        while time.time() - t0 < 3 and not self.find(box):
            time.sleep(0.15)
        self.tap(box, scrolls=0, wait=0.4)
        if not self.type_text(kw):
            self.say(f"  ✗ 设置搜索框输入「{kw}」失败，跳过")
            return False
        t0 = time.time()
        while time.time() - t0 < 2.5 and not self.find(entry or kw, exact=True):   # 搜索结果出来就走
            time.sleep(0.15)
        ok = self.tap(entry or kw, exact=True, scrolls=2, wait=1.0)
        return ok

    def start(self, pkg, activity=None, settle=1.2):
        """拉起 App；之后 settle 秒内冒出来的更新/推荐弹窗顺手点掉。"""
        self.miss = 0
        if activity:
            self.d.shell(f"am start -n {pkg}/{activity}")
        else:
            self.d.app_stop(pkg)
            self.d.shell(f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1")
        t = time.time()
        while time.time() - t < 3 and len(self.texts()) < 3:   # 等首屏画出来
            time.sleep(0.15)
        if len(self.texts()) < 3:          # 还是空白：多半是读不到的全屏广告弹窗，按一次返回关掉
            self.d.shell("input keyevent BACK"); time.sleep(0.8)
            self.say("  · 首屏读不到（广告弹窗？），按了一次返回")
        while time.time() - t < settle:
            self.dismiss()
            time.sleep(0.4)


def main():
    a = sys.argv[1:]
    if len(a) < 3 or a[0] != "-s":
        print(__doc__); sys.exit(1)
    p = Phone(a[1]); cmd, rest = a[2], a[3:]
    if cmd == "ls":
        p.ls()
    elif cmd == "tap":
        for t in rest:
            p.tap(t)
        p.ls()
    elif cmd == "off":
        keep = rest[0].split(",") if rest and rest[0] else ()
        t = time.time(); n = p.off(keep=keep)
        print(f"关了 {n} 个，{time.time()-t:.1f} 秒")
    elif cmd == "scan":
        t = time.time(); seen = {}
        for _ in range(60):
            for k, c, _ in p.switches():
                seen.setdefault(k, c)
            if not p.scroll_more():
                break
        for k, c in seen.items():
            print(f"  [{'开' if c else '关'}] {k}")
        if not seen:
            p.top(); p.ls()
        print(f"{len(seen)} 个开关，开着 {sum(seen.values())} 个，{time.time()-t:.1f} 秒")
    elif cmd == "only":
        t = time.time(); n = p.off(only=rest[0].split(","))
        print(f"关了 {n} 个，{time.time()-t:.1f} 秒")
    elif cmd == "run":
        if p.locked():
            print("✗ 手机锁屏了，先解锁再跑"); sys.exit(2)
        g = {"p": p, "__name__": "__recipe__", "ONLY": rest[1:]}
        src = open(rest[0], encoding="utf-8").read()
        build = p.d.shell("getprop ro.build.display.id").output.strip()
        osv = p.d.shell("getprop ro.mi.os.version.incremental").output.strip()     # 小米：HyperOS 版本号
        m = re.search(r'^BUILD\s*=\s*"([^"]+)"', src, re.M)
        if m and not (build.startswith(m.group(1)) or osv.startswith(m.group(1))):
            os.environ["AAC_REF"] = "1"
            print(f"⚠ 机型脚本是按 {m.group(1)} 录的，这台是 {osv or build}：用安全模式跑（只关点名的开关），没找到的段会快速跳过")
        t = time.time()
        exec(src, g)
        print(f"\n机型脚本跑完：关了 {len(p.changed)} 个，{time.time()-t:.0f} 秒")
        import json, datetime
        import os
        logdir = os.environ.get("AAC_BACKUPS") or os.path.dirname(os.path.abspath(rest[0]))
        try:
            os.makedirs(logdir, exist_ok=True)
            with open(os.path.join(logdir, "run-log.txt"), "a", encoding="utf-8") as f:
                f.write(f"\n# {datetime.datetime.now():%Y-%m-%d %H:%M} {' '.join(rest[1:]) or '全跑'}  {time.time()-t:.0f}s\n")
                for pg, tt in p.changed:
                    f.write(f"{pg}\t{tt}\n")
        except OSError:
            pass
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
