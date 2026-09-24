import os
import time
import unittest

from configmerge import (
    BAD_PATH,
    BAD_REF,
    CYCLE,
    UNKNOWN_PATH,
    UNKNOWN_REF,
    ConfigError,
    merge_config,
    render,
    run_dir,
)
from configmerge.path import parse, resolve, to_text, walk

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = os.path.join(REPO_ROOT, "samples")


def merge(**layers):
    full = {"defaults": {}, "file": {}, "remote": {}, "env": {}, "cli": {}}
    full.update(layers)
    return merge_config(full)


def error_of(**layers):
    try:
        merge(**layers)
    except ConfigError as exc:
        return exc
    raise AssertionError("expected ConfigError")


class PathParsingTests(unittest.TestCase):
    def test_plain_and_nested(self):
        self.assertEqual(parse("server.port"), ("server", "port"))
        self.assertEqual(parse("pools[1].size"), ("pools", 1, "size"))
        self.assertEqual(parse("matrix[0][1]"), ("matrix", 0, 1))
        self.assertEqual(to_text(parse("matrix[0][1]")), "matrix[0][1]")

    def test_bad_path_forms(self):
        defaults = {"server": {"port": 1}, "endpoints": [0, 1]}
        for bad in ("", ".", "server.", ".server", "server..port",
                    "server[", "server[1", "server[].port",
                    "server[a].port", "server[1].", "[0]", "x]"):
            with self.subTest(bad=bad):
                with self.assertRaises(ConfigError) as ctx:
                    resolve(bad, defaults)
                self.assertEqual(ctx.exception.code, BAD_PATH)
                self.assertEqual(ctx.exception.detail, f"path={bad}")

    def test_unknown_path(self):
        defaults = {"server": {"port": 1}, "endpoints": [0, 1]}
        for bad in ("server.hots", "missing", "server.port.x",
                    "endpoints[5]", "endpoints[0].x"):
            with self.subTest(bad=bad):
                with self.assertRaises(ConfigError) as ctx:
                    walk(bad, defaults)
                self.assertEqual(ctx.exception.code, UNKNOWN_PATH)

    def test_valid_array_index(self):
        defaults = {"pools": [{"size": 1}, {"size": 2}]}
        self.assertEqual(walk("pools[1].size", defaults), 2)


class MergeRuleTests(unittest.TestCase):
    def test_scalar_override_per_leaf_priority(self):
        result = merge(
            defaults={"a": 1, "b": {"x": 1, "y": 1}},
            file={"b": {"x": 2}},
            remote={"b": {"y": 3}},
            env={"a": "9"},
            cli={"b.x": "7"},
        )
        self.assertEqual(result, {"a": 9, "b": {"x": 7, "y": 3}})

    def test_null_is_override_missing_is_not(self):
        result = merge(
            defaults={"a": 1, "b": 2},
            file={"a": None},
        )
        self.assertIsNone(result["a"])
        self.assertEqual(result["b"], 2)

    def test_null_replaces_array(self):
        result = merge(
            defaults={"xs": [1, 2, 3]},
            cli={"xs": None},
        )
        self.assertIsNone(result["xs"])

    def test_array_replaced_whole_not_index_merged(self):
        result = merge(
            defaults={"xs": [1, 2, 3]},
            file={"xs": [9]},
        )
        self.assertEqual(result["xs"], [9])

    def test_array_elements_still_addressable(self):
        result = merge(
            defaults={"pools": [{"size": 1}, {"size": 2}]},
            env={"pools[1].size": "20"},
        )
        self.assertEqual(result["pools"][1]["size"], 20)
        self.assertEqual(result["pools"][0]["size"], 1)

    def test_type_mismatch_either_direction(self):
        result = merge(
            defaults={"k": {"x": 1}, "n": 5},
            remote={"k": 5},
            file={"n": {"y": 2}},
        )
        self.assertEqual(result["k"], 5)
        self.assertEqual(result["n"], {"y": 2})

    def test_type_mismatch_on_array_path(self):
        result = merge(
            defaults={"k": {"x": 1}},
            remote={"k": [1, 2]},
        )
        self.assertEqual(result["k"], [1, 2])

    def test_cli_beats_env_beats_others(self):
        result = merge(
            defaults={"v": "d"},
            file={"v": "f"},
            remote={"v": "r"},
            env={"v": '"e"'},
            cli={"v": '"c"'},
        )
        self.assertEqual(result["v"], "c")
        result2 = merge(defaults={"v": "d"}, env={"v": '"e"'})
        self.assertEqual(result2["v"], "e")

    def test_env_cli_string_coercion(self):
        result = merge(
            defaults={"n": 0, "b": False, "nil": 1, "s": "", "arr": []},
            env={"n": "123", "b": "true", "nil": "null", "s": "abc",
                 "arr": "[1, 2]"},
        )
        self.assertEqual(result["n"], 123)
        self.assertIs(result["b"], True)
        self.assertIsNone(result["nil"])
        self.assertEqual(result["s"], "abc")
        self.assertEqual(result["arr"], [1, 2])

    def test_unknown_path_in_nested_file_layer(self):
        err = error_of(defaults={"a": 1}, file={"b": 2})
        self.assertEqual(err.code, UNKNOWN_PATH)
        self.assertEqual(err.detail, "path=b")

    def test_env_validated_before_file_remote(self):
        err = error_of(
            defaults={"a": 1},
            file={"zzz": 1},
            remote={"mmm": 1},
            env={"bad": 1},
        )
        self.assertEqual(err.code, UNKNOWN_PATH)
        self.assertEqual(err.detail, "path=bad")

    def test_env_errors_reported_before_cli(self):
        err = error_of(defaults={"a": 1},
                       env={"bad1": 1, "bad2": 2})
        self.assertEqual(err.detail, "path=bad1")

    def test_bad_path_from_layer_key(self):
        err = error_of(defaults={"server": {"port": 1}},
                       env={"server..port": "1"})
        self.assertEqual(err.code, BAD_PATH)
        self.assertEqual(err.detail, "path=server..port")

    def test_values_are_not_deep_copied_from_layers(self):
        shared = [1, 2, 3]
        result = merge(defaults={"xs": [0]}, cli={"xs": shared})
        self.assertIs(result["xs"], shared)


class ReferenceTests(unittest.TestCase):
    def test_chain_and_overridden_target(self):
        result = merge(
            defaults={"a": "1", "b": "${a}", "c": "${b}"},
            remote={"a": "9"},
        )
        self.assertEqual(result["c"], "9")

    def test_ref_to_array_element(self):
        result = merge(defaults={"xs": ["h1", "h2"], "r": "${xs[1]}"})
        self.assertEqual(result["r"], "h2")

    def test_ref_to_whole_object(self):
        result = merge(defaults={"a": {"x": 1}, "b": "${a}"})
        self.assertEqual(result["b"], {"x": 1})

    def test_remote_override_visible_to_ref(self):
        result = merge(
            defaults={"base": {"v": "d"}, "r": "${base.v}"},
            remote={"base": {"v": "r"}},
        )
        self.assertEqual(result["r"], "r")

    def test_dollar_brace_in_middle_is_literal(self):
        result = merge(defaults={"a": "x${b}/y"})
        self.assertEqual(result["a"], "x${b}/y")

    def test_bad_ref_forms(self):
        for value in ("${a}/b", "${a", "${a}{b}", "${a}b}"):
            with self.subTest(value=value):
                err = error_of(defaults={"a": "x", "r": value})
                self.assertEqual(err.code, BAD_REF)
                self.assertEqual(err.detail, f"value={value}")

    def test_unknown_ref(self):
        err = error_of(defaults={"a": "${missing}"})
        self.assertEqual(err.code, UNKNOWN_REF)
        self.assertEqual(err.detail, "ref=missing")

    def test_unknown_ref_bad_inner_path(self):
        err = error_of(defaults={"a": "${b..c}"})
        self.assertEqual(err.code, UNKNOWN_REF)
        self.assertEqual(err.detail, "ref=b..c")

    def test_cycle_three_nodes(self):
        err = error_of(defaults={"a": "${b}", "b": "${c}",
                                 "c": "${a}", "d": 1})
        self.assertEqual(err.code, CYCLE)
        self.assertEqual(err.detail, "b->c->a->b")
        self.assertEqual(err.line(), "error,CYCLE,b->c->a->b")

    def test_cycle_entered_via_other_node(self):
        err = error_of(defaults={"x": "${y}", "y": "${x}",
                                 "z": "${y}"})
        self.assertEqual(err.code, CYCLE)
        self.assertEqual(err.detail, "y->x->y")

    def test_self_cycle(self):
        err = error_of(defaults={"a": "${a}"})
        self.assertEqual(err.code, CYCLE)
        self.assertEqual(err.detail, "a->a")

    def test_ref_inside_array(self):
        result = merge(defaults={"a": 1, "xs": ["${a}", 2]})
        self.assertEqual(result["xs"], [1, 2])

    def test_ref_target_null(self):
        result = merge(defaults={"a": None, "b": "${a}"})
        self.assertIsNone(result["b"])

    def test_dict_override_of_scalar_not_validated_inside(self):
        result = merge(defaults={"a": 1}, file={"a": {"x": 1}})
        self.assertEqual(result["a"], {"x": 1})


class DeterminismTests(unittest.TestCase):
    def test_key_order_follows_defaults(self):
        result = merge(
            defaults={"b": 1, "a": 2, "c": 3},
            cli={"a": 9},
        )
        self.assertEqual(list(result.keys()), ["b", "a", "c"])
        text = render(result)
        self.assertEqual(
            text.splitlines()[:4],
            ["{", '  "b": 1,', '  "a": 9,', '  "c": 3'],
        )

    def test_repeated_runs_byte_identical(self):
        first, ok1 = run_dir(os.path.join(SAMPLES, "case-6"))
        second, ok2 = run_dir(os.path.join(SAMPLES, "case-6"))
        self.assertTrue(ok1 and ok2)
        self.assertEqual(first, second)


class GoldenSampleTests(unittest.TestCase):
    def test_all_samples(self):
        for case in sorted(os.listdir(SAMPLES)):
            case_dir = os.path.join(SAMPLES, case)
            with self.subTest(case=case):
                output, _ = run_dir(case_dir)
                with open(os.path.join(case_dir, "expected.txt"),
                          encoding="utf-8") as handle:
                    self.assertEqual(output, handle.read())


class PerformanceTests(unittest.TestCase):
    def test_case_six_within_tens_of_ms(self):
        case_dir = os.path.join(SAMPLES, "case-6")
        run_dir(case_dir)  # warm up
        start = time.perf_counter()
        run_dir(case_dir)
        elapsed_ms = (time.perf_counter() - start) * 1000
        self.assertLess(elapsed_ms, 100, f"took {elapsed_ms:.1f} ms")


class CliTests(unittest.TestCase):
    def test_success_and_failure_exit_codes(self):
        import subprocess
        import sys

        proc_ok = subprocess.run(
            [sys.executable, "-m", "configmerge",
             os.path.join(SAMPLES, "case-1")],
            capture_output=True, text=True, cwd=REPO_ROOT)
        self.assertEqual(proc_ok.returncode, 0)
        self.assertTrue(proc_ok.stdout.endswith("}\n"))

        proc_bad = subprocess.run(
            [sys.executable, "-m", "configmerge",
             os.path.join(SAMPLES, "case-4")],
            capture_output=True, text=True, cwd=REPO_ROOT)
        self.assertEqual(proc_bad.returncode, 1)
        self.assertEqual(proc_bad.stdout.strip(),
                         "error,CYCLE,b->c->a->b")


if __name__ == "__main__":
    unittest.main()
