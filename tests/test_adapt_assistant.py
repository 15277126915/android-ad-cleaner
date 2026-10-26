"""新机型适配辅助（adapt）：TSV 解析、草稿生成格式、探路导航中断、适配报告与 mock 回读一致。

运行：python -m unittest discover -s tests -v
"""
import contextlib
import io
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tool"))
import adapt
import explore
import run

TSV = """包名\t页面\t开关\t状态\t像广告\t人工勾选
# 在末列写「关」挑出要关的开关
com.heytap.market\t设置 > 隐私\t个性化推荐\t开\t★\t关
com.heytap.market\t设置 > 隐私\t应用安全\t开\t\t
com.heytap.market\t设置 > 服务管理\t活动弹窗\t开\t★\t
com.heytap.market\t设置\t限制广告跟踪\t开\t★\t关
com.heytap.browser\t设置 > 隐私\t个性化推荐\t开\t★\t是
com.heytap.browser\t\t（没找到设置入口）\t\t\t
"""


def write_tsv(directory, text=TSV, name="探路-PJA110.tsv"):
    path = Path(directory) / name
    path.write_bytes(b"\xef\xbb\xbf" + text.replace("\n", "\r\n").encode("utf-8"))   # BOM + CRLF
    return path


def draft_phone(switch_lists, tap_ok=True):
    """能跑草稿的 Mock 手机：入口都点得到，开关状态按 switch_lists 回读。"""
    p = Mock()
    p.W, p.H, p.miss, p.changed = 1168, 1712, 0, []
    p.locked.return_value = False
    p.find.return_value = None
    p.tap.return_value = tap_ok
    p.scroll_more.return_value = False
    p.top.return_value = None
    p.off.return_value = 0
    p.switches.side_effect = switch_lists
    p.d.shell.return_value = types.SimpleNamespace(output="PJA110_14.0.0.812")
    return p


class TsvParseTests(unittest.TestCase):
    def test_bom_crlf_comment_and_header_are_tolerated(self):
        with tempfile.TemporaryDirectory() as d:
            rows = adapt.parse_tsv(write_tsv(d))
        self.assertEqual([r["pkg"] for r in rows],
                         ["com.heytap.market"] * 4 + ["com.heytap.browser"] * 2)
        self.assertEqual(rows[0]["title"], "个性化推荐")
        self.assertEqual(rows[0]["pick"], "关")
        self.assertEqual(rows[-1]["title"], "（没找到设置入口）")

    def test_legacy_five_column_tsv_is_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "old.tsv"
            path.write_text("com.a\t设置\t个性化推荐\t开\t★\n", encoding="utf-8")
            rows = adapt.parse_tsv(path)
        self.assertEqual(rows[0]["pick"], "")

    def test_missing_tsv_fails_clearly(self):
        with self.assertRaises(SystemExit):
            adapt.read_pick_file("/不存在的清单.txt")


class SelectionTests(unittest.TestCase):
    def test_marks_and_pick_file_select_only_human_choices(self):
        with tempfile.TemporaryDirectory() as d:
            rows = adapt.parse_tsv(write_tsv(d))
            pick = Path(d) / "pick.txt"
            pick.write_text("# 人工确认\n活动弹窗\n", encoding="utf-8")
            groups, protection, ad_left = adapt.select_rows(rows, adapt.read_pick_file(pick))
        self.assertEqual(groups, [
            ("com.heytap.market", "设置 > 隐私", ["个性化推荐"]),
            ("com.heytap.market", "设置 > 服务管理", ["活动弹窗"]),
            ("com.heytap.browser", "设置 > 隐私", ["个性化推荐"]),
        ])
        self.assertEqual(protection, ["限制广告跟踪"])     # 勾了也不写进草稿
        self.assertEqual(ad_left, 0)

    def test_protection_switch_marked_still_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            rows = adapt.parse_tsv(write_tsv(d))
            groups, protection, _ = adapt.select_rows(rows)
        self.assertNotIn("限制广告跟踪", [n for _, _, names in groups for n in names])
        self.assertEqual(protection, ["限制广告跟踪"])

    def test_unmarked_suspected_ad_switch_is_reported_not_selected(self):
        with tempfile.TemporaryDirectory() as d:
            rows = adapt.parse_tsv(write_tsv(d))
            groups, _, ad_left = adapt.select_rows(rows)
        titles = [n for _, _, names in groups for n in names]
        self.assertNotIn("活动弹窗", titles)
        self.assertEqual(ad_left, 1)


class DraftGenTests(unittest.TestCase):
    def gen(self, directory, extra=()):
        out = Path(directory) / "草稿.py"
        with contextlib.redirect_stdout(io.StringIO()):
            adapt.cmd_gen([str(write_tsv(directory)), "-o", str(out), *extra])
        return out.read_text(encoding="utf-8")

    def test_draft_header_carries_build_models_and_unverified_marks(self):
        with tempfile.TemporaryDirectory() as d:
            src = self.gen(d)
        self.assertIn('BUILD = ""', src)
        self.assertIn('MODELS = ["PJA110"]', src)                    # 型号从文件名认出
        self.assertIn("待验证草稿", src)
        self.assertIn("这不是适配成果", src)
        self.assertIn("不要直接放进 recipes/", src)
        compile(src, "草稿.py", "exec")                              # 生成物必须是合法 Python

    def test_step_literal_format_survives_run_recipe_meta(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "草稿.py"
            with contextlib.redirect_stdout(io.StringIO()):
                adapt.cmd_gen([str(write_tsv(d)), "-o", str(out)])
            meta = run.recipe_meta(str(out))
        self.assertEqual(meta["steps"], ["com.heytap.market · 设置 > 隐私", "com.heytap.browser · 设置 > 隐私"])
        self.assertEqual(meta["models"], ["PJA110"])
        self.assertEqual(meta["build"], "")

    def test_switches_are_written_as_named_only_list(self):
        with tempfile.TemporaryDirectory() as d:
            src = self.gen(d)
        self.assertIn('close_named(["个性化推荐"], "设置 > 隐私")', src)
        self.assertIn('p.off(only=names, page=page, max_screens=max_screens)', src)
        self.assertNotIn("keep=", src)                               # 草稿不做整页全关

    def test_navigation_paths_come_from_explore(self):
        with tempfile.TemporaryDirectory() as d:
            src = self.gen(d)
        self.assertIn('require(p.tap("设置", exact=True, scrolls=3), "未找到设置入口「设置」")', src)
        self.assertIn('require(p.tap("隐私", exact=True, scrolls=4), "未找到子页入口「隐私」")', src)

    def test_model_and_build_options_override(self):
        with tempfile.TemporaryDirectory() as d:
            src = self.gen(d, ["--model", "PLP120", "--build", "PLP120_16.0.9"])
        self.assertIn('BUILD = "PLP120_16.0.9"', src)
        self.assertIn('MODELS = ["PLP120"]', src)

    def test_no_selection_refuses_to_generate(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "empty.tsv"
            path.write_text("com.a\t设置\t个性化推荐\t开\t★\t\n", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit):
                    adapt.cmd_gen([str(path), "-o", str(Path(d) / "x.py")])


class CheckReportTests(unittest.TestCase):
    def draft(self, directory):
        out = Path(directory) / "草稿.py"
        with contextlib.redirect_stdout(io.StringIO()):
            adapt.cmd_gen([str(write_tsv(directory)), "-o", str(out)])
        return out

    def test_all_closed_report_matches_readback(self):
        with tempfile.TemporaryDirectory() as d:
            out = self.draft(d)
            p = draft_phone([[("个性化推荐", True, (1, 2))], [("个性化推荐", False, (1, 2))]] * 2)
            with patch.dict(os.environ), contextlib.redirect_stdout(io.StringIO()):
                report = adapt.check_draft(p, str(out))
                self.assertEqual(os.environ.get("AAC_REF"), "1")   # 安全模式已置位
        self.assertEqual(report, {"verified": 2, "missing": [], "pending": [], "failed_steps": []})
        self.assertTrue(adapt.print_report(report))
        self.assertEqual(p.off.call_count, 2)

    def test_missing_switch_is_reported_not_clicked(self):
        with tempfile.TemporaryDirectory() as d:
            out = self.draft(d)
            p = draft_phone([[("别的开关", True, (1, 2))]] * 10)
            with patch.dict(os.environ), contextlib.redirect_stdout(io.StringIO()):
                report = adapt.check_draft(p, str(out))
        self.assertEqual(report["verified"], 0)
        self.assertEqual(report["missing"], ["个性化推荐", "个性化推荐"])
        p.off.assert_not_called()
        self.assertFalse(adapt.print_report(report))

    def test_unconfirmed_readback_is_pending_not_success(self):
        with tempfile.TemporaryDirectory() as d:
            out = self.draft(d)
            p = draft_phone([[("个性化推荐", True, (1, 2))]] * 10)
            with patch.dict(os.environ), contextlib.redirect_stdout(io.StringIO()):
                report = adapt.check_draft(p, str(out))
        self.assertEqual(report["verified"], 0)
        self.assertEqual(report["pending"], ["个性化推荐", "个性化推荐"])
        self.assertEqual(p.off.call_count, 2)                       # 点了但回读没确认
        self.assertFalse(adapt.print_report(report))

    def test_failed_entry_lands_in_failed_steps(self):
        with tempfile.TemporaryDirectory() as d:
            out = self.draft(d)
            p = draft_phone([], tap_ok=False)
            with patch.dict(os.environ), contextlib.redirect_stdout(io.StringIO()):
                report = adapt.check_draft(p, str(out))
        self.assertEqual(report["verified"], 0)
        self.assertEqual(report["failed_steps"],
                         ["com.heytap.market · 设置 > 隐私", "com.heytap.browser · 设置 > 隐私"])

    def test_partial_completion_is_never_worded_as_success(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ok = adapt.print_report({"verified": 1, "missing": [], "pending": ["活动弹窗"], "failed_steps": []})
        self.assertFalse(ok)
        self.assertIn("部分完成", out.getvalue())
        self.assertIn("不能把部分完成当成适配成功", out.getvalue())


class ExploreNavigationTests(unittest.TestCase):
    def entry_phone(self, focus_seq, tap_seq):
        p = Mock()
        p.W, p.H = 1168, 1712
        p.switches.return_value = []
        p.scroll_more.return_value = False
        p.top.return_value = None
        p.focus.side_effect = focus_seq
        p.tap.side_effect = tap_seq

        def node(text):
            return ET.fromstring(f'<node text="{text}" package="com.example" bounds="[60,300][600,360]"/>')

        names = ["隐私", "通知", "电池"]
        p.texts.return_value = [(n, (60, 300, 600, 360), node(n)) for n in names]
        return p

    def test_back_to_home_is_bounded_and_reports_reason(self):
        p = Mock(); p.focus.return_value = "com.example/.Sub"
        reason = explore.back_to(p, "com.example/.Settings", tries=3)
        self.assertIn("com.example/.Sub", reason)
        self.assertEqual(p.back.call_count, 3)                      # 有界，不会一直按返回

    def test_back_to_home_stops_as_soon_as_settings_page_is_back(self):
        p = Mock(); p.focus.side_effect = ["com.example/.Sub", "com.example/.Sub", "com.example/.Settings"]
        self.assertIsNone(explore.back_to(p, "com.example/.Settings"))
        self.assertEqual(p.back.call_count, 2)

    def test_stuck_subpage_stops_package_without_endless_restarts(self):
        p = self.entry_phone(["com.example/.Settings"] + ["com.example/.Sub"] * 10,
                             [True, True, True, False, False, False])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            explore.explore(p, "com.example", [])
        self.assertIn("探路到此为止", out.getvalue())
        self.assertEqual(p.back.call_count, 3)
        self.assertEqual(p.start.call_count, 2)                     # 首次 + 一次恢复，不反复重启
        p.d.app_stop.assert_called_once_with("com.example")
        tapped = [c.args[0] for c in p.tap.call_args_list]
        self.assertNotIn("通知", tapped)
        self.assertNotIn("电池", tapped)

    def test_recovered_settings_page_continues_remaining_entries(self):
        p = self.entry_phone(["com.example/.Settings"] + ["com.example/.Sub"] * 4 + ["com.example/.Settings2"] * 8,
                             [True] * 7)
        with contextlib.redirect_stdout(io.StringIO()):
            explore.explore(p, "com.example", [])
        tapped = [c.args[0] for c in p.tap.call_args_list]
        for entry in ("隐私", "通知", "电池"):
            self.assertIn(entry, tapped)
        self.assertEqual(p.start.call_count, 2)
        self.assertEqual(p.back.call_count, 3)                      # 只有第一次回不去时按了返回
        p.d.app_stop.assert_called_once_with("com.example")


if __name__ == "__main__":
    unittest.main()
