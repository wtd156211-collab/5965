import json
import os
import time
import unittest

from configmerge import ConfigError, merge_layers, render, run_case
from configmerge.merging import deep_merge, parse_flat_value
from configmerge.paths import canonical, parse_path

SAMPLES = os.path.join(os.path.dirname(__file__), os.pardir, "samples")


class SampleCasesTest(unittest.TestCase):
    def test_all_sample_cases(self):
        for name in sorted(os.listdir(SAMPLES)):
            case_dir = os.path.join(SAMPLES, name)
            if not os.path.isdir(case_dir):
                continue
            with self.subTest(case=name):
                with open(os.path.join(case_dir, "expected.txt"), encoding="utf-8") as fh:
                    expected = fh.read()
                self.assertEqual(run_case(case_dir), expected)

    def test_determinism_byte_identical(self):
        case_dir = os.path.join(SAMPLES, "case-6")
        first = run_case(case_dir)
        second = run_case(case_dir)
        self.assertEqual(first, second)

    def test_performance_case6(self):
        case_dir = os.path.join(SAMPLES, "case-6")
        start = time.perf_counter()
        run_case(case_dir)
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 0.5, f"case-6 合并耗时 {elapsed * 1000:.1f}ms")


class PathTest(unittest.TestCase):
    def test_parse_ok(self):
        self.assertEqual(parse_path("server.port"), ("server", "port"))
        self.assertEqual(parse_path("pools[1].size"), ("pools", 1, "size"))
        self.assertEqual(parse_path("matrix[0][1]"), ("matrix", 0, 1))
        self.assertEqual(parse_path("a"), ("a",))

    def test_parse_bad(self):
        for raw in ("", ".a", "a.", "a..b", "a[]", "a[x]", "a[1", "a]", "[1]"):
            with self.subTest(path=raw):
                with self.assertRaises(ConfigError) as ctx:
                    parse_path(raw)
                self.assertEqual(ctx.exception.code, "BAD_PATH")
                self.assertEqual(ctx.exception.detail, f"path={raw}")

    def test_canonical_roundtrip(self):
        for raw in ("server.port", "pools[1].size", "matrix[0][1]"):
            self.assertEqual(canonical(parse_path(raw)), raw)


class FlatValueTest(unittest.TestCase):
    def test_json_strings(self):
        self.assertEqual(parse_flat_value("123"), 123)
        self.assertIs(parse_flat_value("true"), True)
        self.assertIsNone(parse_flat_value("null"))
        self.assertEqual(parse_flat_value("[1, 2]"), [1, 2])

    def test_plain_strings(self):
        self.assertEqual(parse_flat_value("10.0.0.5"), "10.0.0.5")
        self.assertEqual(parse_flat_value("hello"), "hello")

    def test_non_string_passthrough(self):
        self.assertEqual(parse_flat_value(20), 20)
        self.assertIsNone(parse_flat_value(None))
        self.assertEqual(parse_flat_value(["y", "z"]), ["y", "z"])


class MergeRuleTest(unittest.TestCase):
    def test_deep_merge_leaf_priority(self):
        low = {"a": {"x": 1, "y": 2}, "b": 1}
        high = {"a": {"x": 9}}
        self.assertEqual(deep_merge(low, high), {"a": {"x": 9, "y": 2}, "b": 1})

    def test_array_replaced_wholesale(self):
        self.assertEqual(deep_merge({"l": [1, 2, 3]}, {"l": [4]}), {"l": [4]})

    def test_null_overrides_and_missing_keeps(self):
        merged = merge_layers(
            {"a": 1, "b": 2}, {"a": None}, {}, {}, {}
        )
        self.assertEqual(merged, {"a": None, "b": 2})

    def test_type_change_replaces(self):
        self.assertEqual(deep_merge({"a": {"x": 1}}, {"a": 5}), {"a": 5})
        self.assertEqual(deep_merge({"a": 5}, {"a": {"x": 1}}), {"a": {"x": 1}})

    def test_key_order_follows_defaults(self):
        merged = merge_layers(
            {"z": 1, "a": 2, "m": {"b": 1, "a": 2}},
            {"m": {"a": 9}}, {}, {}, {},
        )
        self.assertEqual(list(merged), ["z", "a", "m"])
        self.assertEqual(list(merged["m"]), ["b", "a"])

    def test_no_full_tree_copy(self):
        # 未被覆盖的子树应结构化共享，不做深拷贝
        low = {"big": {"x": [1, 2, 3]}, "small": 1}
        merged = deep_merge(low, {"small": 2})
        self.assertIs(merged["big"], low["big"])


class LayerCheckTest(unittest.TestCase):
    def test_unknown_path_reported_at_load(self):
        with self.assertRaises(ConfigError) as ctx:
            merge_layers({"server": {"host": 1}}, {}, {}, {"server.hots": "x"}, {})
        self.assertEqual(ctx.exception.code, "UNKNOWN_PATH")
        self.assertEqual(ctx.exception.detail, "path=server.hots")

    def test_bad_path_beats_merge(self):
        # 路径错误在合并前就报出
        with self.assertRaises(ConfigError) as ctx:
            merge_layers({"a": 1}, {"a": 2}, {}, {"a..b": 1}, {})
        self.assertEqual(ctx.exception.code, "BAD_PATH")

    def test_env_checked_before_cli(self):
        with self.assertRaises(ConfigError) as ctx:
            merge_layers({"a": 1}, {}, {}, {"a.x": 1}, {"a..y": 1})
        self.assertEqual(ctx.exception.code, "UNKNOWN_PATH")

    def test_env_cli_override_by_path(self):
        merged = merge_layers(
            {"pools": [{"size": 1}, {"size": 2}], "host": "a"},
            {}, {},
            {"host": "10.0.0.5"},
            {"pools[1].size": 20},
        )
        self.assertEqual(merged["host"], "10.0.0.5")
        self.assertEqual(merged["pools"][1]["size"], 20)
        self.assertEqual(merged["pools"][0]["size"], 1)


class RefTest(unittest.TestCase):
    def test_chained_and_remote_visible(self):
        merged = merge_layers(
            {"base": "x", "mid": "${base}", "top": "${mid}"},
            {}, {"base": "y"}, {}, {},
        )
        self.assertEqual(merged, {"base": "y", "mid": "y", "top": "y"})

    def test_ref_to_array_element(self):
        merged = merge_layers(
            {"hosts": ["h1", "h2"], "pick": "${hosts[1]}"}, {}, {}, {}, {}
        )
        self.assertEqual(merged["pick"], "h2")

    def test_ref_to_non_string(self):
        merged = merge_layers({"n": 42, "r": "${n}"}, {}, {}, {}, {})
        self.assertEqual(merged["r"], 42)

    def test_cycle_detail(self):
        with self.assertRaises(ConfigError) as ctx:
            merge_layers({"a": "${b}", "b": "${c}", "c": "${a}"}, {}, {}, {}, {})
        self.assertEqual(ctx.exception.code, "CYCLE")
        self.assertEqual(ctx.exception.detail, "b->c->a->b")

    def test_self_cycle(self):
        with self.assertRaises(ConfigError) as ctx:
            merge_layers({"a": "${a}"}, {}, {}, {}, {})
        self.assertEqual(ctx.exception.code, "CYCLE")
        self.assertEqual(ctx.exception.detail, "a->a")

    def test_unknown_ref(self):
        with self.assertRaises(ConfigError) as ctx:
            merge_layers({"a": "${nope}"}, {}, {}, {}, {})
        self.assertEqual(ctx.exception.code, "UNKNOWN_REF")
        self.assertEqual(ctx.exception.detail, "ref=nope")

    def test_bad_ref(self):
        for value in ("${a}/b", "${a}${b}", "${", "${}"):
            with self.subTest(value=value):
                with self.assertRaises(ConfigError) as ctx:
                    merge_layers({"a": value, "b": 1}, {}, {}, {}, {})
                self.assertEqual(ctx.exception.code, "BAD_REF")
                self.assertEqual(ctx.exception.detail, f"value={value}")

    def test_dollar_brace_mid_string_is_plain(self):
        merged = merge_layers({"a": "x${b}", "b": 1}, {}, {}, {}, {})
        self.assertEqual(merged["a"], "x${b}")


class RenderTest(unittest.TestCase):
    def test_render_format(self):
        text = render({"a": 1, "b": {"c": [1, 2]}})
        self.assertEqual(text, '{\n  "a": 1,\n  "b": {\n    "c": [\n      1,\n      2\n    ]\n  }\n}\n')

    def test_render_stable_across_runs(self):
        layers = ({"b": 1, "a": {"y": 1, "x": 2}}, {}, {}, {}, {})
        self.assertEqual(render(merge_layers(*layers)), render(merge_layers(*layers)))


if __name__ == "__main__":
    unittest.main()
