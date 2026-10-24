# 小米 18 Pro Max（M154FF，HyperOS 4）菜谱。路径 2026-10-22 实测，菜谱整段跑待验证
BUILD = "OS4.0"
import time

ONLY = globals().get("ONLY") or []


def step(name):
    def deco(f):
        if (not ONLY or name in ONLY) and p.locked():
            print(f"\n== {name}：手机锁屏了，后面的都不跑"); return f
        if not ONLY or name in ONLY:
            print(f"\n== {name}"); p.miss = 0
            t = time.time()
            try:
                f()
            except Exception as e:
                print(f"  ✗ 出错：{e}")
            print(f"  ({time.time()-t:.0f} 秒)")
        return f
    return deco


def gear():
    """很多小米 App 的设置是右上角齿轮图标，没有文字。"""
    for n in p.tree().iter("node"):
        d = (n.get("content-desc") or "") + (n.get("resource-id") or "")
        if any(k in d.lower() for k in ("设置", "setting")) and n.get("clickable") == "true":
            from fast import bounds
            l, t, r, b = bounds(n); p.click((l + r) // 2, (t + b) // 2); time.sleep(1)
            return True
    return p.tap("设置", exact=True, scrolls=0)


@step("系统广告")
def _():
    p.setting("个性化广告推荐", "个性化广告推荐", box="搜索")
    p.off(only=["个性化广告推荐"], page="系统·广告服务")


@step("应用商店")
def _():
    p.start("com.xiaomi.market")
    p.go("我的", "设置")
    gear()
    if p.tap("隐私", exact=False):
        p.off(only=["个性化服务"], page="商店·隐私"); p.back()
    if p.tap("模式切换", exact=True):
        p.tap("极简模式", exact=True, scrolls=0); p.confirm(); p.back()
    if p.tap("通知设置", exact=True):
        p.off(only=["新手帮助"], keep=["应用更新"], page="商店·通知"); p.back()
    p.back(2)


@step("手机管家")
def _():
    p.start("com.miui.securitycenter")
    gear()
    if p.tap("隐私设置", exact=True):
        p.off(only=["个性化推荐"], page="管家·隐私"); p.back()
    if p.tap("垃圾清理", exact=True):
        p.off(only=["推荐内容"], page="管家·垃圾清理"); p.back()
    p.back(2)


@step("下载管理")
def _():
    p.start("com.android.providers.downloads.ui")
    gear()
    if p.tap("信息流设置", exact=True):
        p.off(only=["资源推荐", "热榜推荐"], page="下载管理·信息流")
    p.back(3)


@step("主题")
def _():
    p.start("com.android.thememanager")
    p.go("我的", "设置")
    gear()
    p.off(only=["每次联网时通知"], page="主题·设置")
    if p.tap("隐私设置", exact=True):
        p.off(only=["个性化推荐"], page="主题·隐私"); p.back()
    p.back(2)


@step("浏览器")
def _():
    # 首页保持「默认」版（机主决定不改）
    p.start("com.android.browser")
    p.go("我的", "设置")
    gear()
    for page, only in [("主页设置", ["宫格位推送"]), ("搜索设置", ["猜你想搜"]),
                       ("功能设置", ["小说"]), ("隐私和安全", ["个性化内容推荐", "个性化广告推荐"])]:
        if p.tap(page, exact=True):
            p.off(only=only, page=f"浏览器·{page}"); p.back()
    p.back(2)


@step("全局搜索")
def _():
    p.start("com.android.quicksearchbox")
    gear()
    if p.tap("首页展示模块", exact=True):
        p.off(only=["搜索提示词"], page="搜索·首页模块"); p.back()
    if p.tap("应用推荐", exact=True):
        p.off(only=["推荐未安装应用"], page="搜索·应用推荐"); p.back()
    if p.tap("热搜榜单", exact=True):
        p.off(page="搜索·热搜榜单"); p.back()       # 推荐/微博/资讯/全网/影视/音乐/小说/知乎 全关
    p.back(2)


@step("负一屏")
def _():
    p.start("com.miui.personalassistant", ".settings.PASettingActivity")
    p.off(only=["推荐卡片", "热门活动"], page="负一屏·设置")    # 搜索框、出行助手保留
    if p.tap("隐私设置", exact=True):
        p.off(only=["个性化推荐"], page="负一屏·隐私"); p.back()
    p.back()
