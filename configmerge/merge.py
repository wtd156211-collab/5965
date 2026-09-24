"""五层分层合并。

按需遍历，不做整树深拷贝：

1. defaults 递归展平成 (路径元组 -> 叶子值) 映射：dict 与 list 都向下
   递归（数组元素可以用下标路径定位，如 pools[1].size），标量（含 null）
   才是叶子。路径元组里字符串是对象键、整数是数组下标。
2. 其它层递归遍历自身：仅当「层值与默认值同位置都是对象」时才继续下钻；
   否则整个值作为该路径的叶子覆盖（数组整体替换、类型不同整体覆盖）。
   每个叶子路径都对照默认值树校验。层内按 UTF-8 键序遍历，报错顺序确定。
   路径解析结果有缓存，同一文本只解析一次。
3. 输出按默认值树原始键序/数组序重建：某路径被高层整体给值（身份已不是
   默认节点）就原样使用，否则逐元素套用叶子覆盖。叶子值直接引用，不复制。
"""

import json

from .path import resolve

# 五层从低到高
LAYER_NAMES = ("defaults", "file", "remote", "env", "cli")

# env/cli 在合并前先单独校验路径（检查顺序见 README）
FLAT_LAYERS = ("env", "cli")

_MISSING = object()


def _flatten_defaults(obj, out, out_path):
    if isinstance(obj, dict):
        for key in obj.keys():
            _flatten_defaults(obj[key], out, out_path + (key,))
    elif isinstance(obj, list):
        for index, item in enumerate(obj):
            _flatten_defaults(item, out, out_path + (index,))
    else:
        out[out_path] = obj


def _walk_layer(obj, out_path, text, default_node, leaves, cache):
    """递归展开一层配置并覆盖 leaves。

    仅当层值与默认值同位置都是对象时递归；否则值整体作为叶子覆盖。
    """
    if isinstance(obj, dict) and isinstance(default_node, dict):
        for key in sorted(obj.keys()):
            child_text = key if text == "" else text + "." + key
            segments, child_default = resolve(
                key, default_node, cache, display=child_text)
            _walk_layer(obj[key], out_path + segments, child_text,
                        child_default, leaves, cache)
    else:
        if out_path:
            leaves[out_path] = obj


def coerce_strings(layer):
    """env/cli 层值规则：字符串按 JSON 解析，解析不了保留为原字符串。"""
    result = {}
    for key, value in layer.items():
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                pass
        result[key] = value
    return result


def merge_layers(layers):
    """合并五层，返回 (leaves, default_tree)。"""
    defaults = layers["defaults"]
    leaves = {}
    _flatten_defaults(defaults, leaves, ())

    cache = {}
    # 检查顺序：先校验 env、cli 两层的路径（按 UTF-8 键序），出错立刻返回
    for name in FLAT_LAYERS:
        layer = layers.get(name) or {}
        for key in sorted(layer.keys()):
            resolve(key, defaults, cache)

    for name in LAYER_NAMES[1:]:
        layer = layers.get(name)
        if layer is None:
            continue
        _walk_layer(layer, (), "", defaults, leaves, cache)

    return leaves, defaults


def build_output(leaves, default_tree):
    """按默认值树的键序与数组顺序重建合并结果对象。"""

    def build(node, path):
        current = leaves.get(path, _MISSING)
        if current is not _MISSING:
            return current
        if isinstance(node, dict):
            return {key: build(node[key], path + (key,))
                    for key in node.keys()}
        if isinstance(node, list):
            return [build(item, path + (index,))
                    for index, item in enumerate(node)]
        return leaves[path]

    return build(default_tree, ())
