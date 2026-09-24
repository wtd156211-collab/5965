"""分层配置合并库。

五层（defaults < file < remote < env < cli）按优先级合并：
对象深合并、数组整体替换、null 算覆盖；嵌套路径加载期校验；
${路径} 引用在合并结果上解析，循环引用报错。
"""

import json
import os

from .errors import (
    BAD_PATH,
    BAD_REF,
    CYCLE,
    UNKNOWN_PATH,
    UNKNOWN_REF,
    ConfigError,
)
from .merge import (
    LAYER_NAMES,
    build_output,
    coerce_strings,
    merge_layers,
)
from .refs import resolve_refs

__all__ = [
    "BAD_PATH",
    "BAD_REF",
    "CYCLE",
    "UNKNOWN_PATH",
    "UNKNOWN_REF",
    "ConfigError",
    "LAYER_NAMES",
    "merge_config",
    "render",
    "load_layers",
    "run_dir",
]


def merge_config(layers):
    """五层合并并解析引用，返回结果树（dict）。

    layers 至少包含 "defaults"；env、cli 层的字符串值会先按 JSON 解析。
    任何校验/引用错误抛 ConfigError。
    """
    prepared = dict(layers)
    for name in ("env", "cli"):
        if prepared.get(name) is not None:
            prepared[name] = coerce_strings(prepared[name])

    leaves, defaults = merge_layers(prepared)
    output = build_output(leaves, defaults)
    resolve_refs(output)
    return output


def render(output):
    """输出固定格式 JSON：缩进 2 空格、LF 结尾。"""
    return json.dumps(output, indent=2) + "\n"


def load_layers(case_dir):
    """从目录读取五层 JSON，缺失的高层按空对象处理；defaults 必填。"""
    layers = {}
    for name in LAYER_NAMES:
        path = os.path.join(case_dir, name + ".json")
        if not os.path.exists(path):
            if name == "defaults":
                raise FileNotFoundError(f"required file missing: {path}")
            layers[name] = {}
        else:
            with open(path, encoding="utf-8") as handle:
                layers[name] = json.load(handle)
    return layers


def run_dir(case_dir):
    """跑一个用例目录，返回 (输出文本, 是否成功)。"""
    layers = load_layers(case_dir)
    try:
        output = merge_config(layers)
    except ConfigError as error:
        return error.line() + "\n", False
    return render(output), True
