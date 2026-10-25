"""不能作为营销渠道关闭的功能通知；未知包名和渠道 ID 不猜测。"""
import re


PHOTO_SPOT = re.compile(r"找[机機]位|[机機]位推[荐薦]|推[荐薦][机機]位")


def protected_channel(name, channel_id="", list_label=""):
    # 名称可能带空格 / 零宽字符；当前名称、ID、旧清单描述任一命中就保留。
    text = re.sub(r"[\s\u200b\ufeff]+", "", " ".join((name, channel_id, list_label)))
    return bool(PHOTO_SPOT.search(text))
