"""分层配置合并库。

五层按优先级从低到高合并：defaults < file < remote < env < cli。
defaults 必填，同时定义合法路径集合；env / cli 是「路径 -> 值」的
扁平映射，路径在加载阶段校验，写错立刻报错。

用法（库）::

    from configmerge import merge_layers, render, ConfigError

    try:
        result = merge_layers(defaults, file, remote, env, cli)
        text = render(result)
    except ConfigError as exc:
        text = exc.render()          # error,<code>,<detail>

用法（命令行）::

    python -m configmerge samples/case-1
"""

import json
import os

from .errors import ConfigError
from .merging import apply_flat_layer, parse_flat_value
from .paths import parse_path, validate_path
from .refs import RefResolver, collect_refs, substitute

__all__ = [
    "ConfigError",
    "merge_layers",
    "render",
    "run_case",
    "load_case",
    "LAYER_FILES",
]

LAYER_FILES = ("defaults", "file", "remote", "env", "cli")


def _prepare_layer(flat, defaults, parse_values):
    """解析并校验一层的「路径 -> 值」映射，按键在文件里的顺序返回
    [(原始路径, 段元组, 值)]。路径出错立即抛 ConfigError。

    每一层的键都按路径解析（单段路径就是顶层键，所以嵌套树写法
    等价于顶层路径加对象值）；env / cli 的值来自字符串，按 JSON
    解析，file / remote 的值原样使用。
    """
    entries = []
    for raw, value in flat.items():
        segments = parse_path(raw)              # BAD_PATH
        validate_path(segments, defaults, raw)  # UNKNOWN_PATH
        if parse_values:
            value = parse_flat_value(value)
        entries.append((raw, segments, value))
    return entries


def merge_layers(defaults, file, remote, env, cli):
    """合并五层配置并解析引用，返回最终配置树。

    检查顺序：先解析并校验 env、cli 两层的路径（出错立刻抛
    ConfigError），再解析 file、remote 两层并合并五层，最后解析引用。
    """
    env_entries = _prepare_layer(env, defaults, parse_values=True)
    cli_entries = _prepare_layer(cli, defaults, parse_values=True)
    file_entries = _prepare_layer(file, defaults, parse_values=False)
    remote_entries = _prepare_layer(remote, defaults, parse_values=False)

    tree = defaults
    for entries in (file_entries, remote_entries, env_entries, cli_entries):
        tree = apply_flat_layer(tree, entries)

    refs = {}
    collect_refs(tree, refs)  # BAD_REF
    resolver = RefResolver(tree, refs)
    resolver.resolve_all()    # UNKNOWN_REF / CYCLE
    return substitute(tree, refs, resolver.memo)


def render(result):
    """输出合并结果：缩进 2 空格、行尾 LF、键序固定，末尾补一个 LF。"""
    return json.dumps(result, indent=2, ensure_ascii=False) + "\n"


def load_case(case_dir):
    """从目录读入五层 JSON，返回 (defaults, file, remote, env, cli)。"""
    layers = []
    for name in LAYER_FILES:
        with open(os.path.join(case_dir, name + ".json"), encoding="utf-8") as fh:
            layers.append(json.load(fh))
    return tuple(layers)


def run_case(case_dir):
    """跑一个用例目录，返回输出文本（合并 JSON 或 error 行）。"""
    try:
        return render(merge_layers(*load_case(case_dir)))
    except ConfigError as exc:
        return exc.render() + "\n"
