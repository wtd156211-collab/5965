"""五层合并：树层深合并 + 扁平层（env/cli）按路径覆盖。

性能要点：合并不可变、结构化共享。deep_merge 只在两边都是对象的
重叠路径上建新 dict，其余子树直接引用复用；扁平层按路径覆盖时只
复制路径脊柱（深度 ≤ 7），从不对整棵树做深拷贝。
"""

import json


def deep_merge(low, high):
    """深合并两层。两边都是 dict 时逐键递归；其余情况 high 整体替换 low
    （数组整体替换、null 算一次覆盖、类型不同整体覆盖都走这里）。"""
    if isinstance(low, dict) and isinstance(high, dict):
        merged = {}
        for key, value in low.items():
            if key in high:
                merged[key] = deep_merge(value, high[key])
            else:
                merged[key] = value
        for key, value in high.items():
            if key not in low:
                merged[key] = value
        return merged
    return high


def parse_flat_value(value):
    """env/cli 层的值：字符串按 JSON 解析，解析不了按原样字符串；
    非字符串（数字 / 布尔 / null / 数组 / 对象）原样使用。"""
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except ValueError:
        return value


def apply_override(node, segments, value):
    """把 value 按路径写进树里，返回新树（只复制路径脊柱）。

    叶子处沿用层合并语义：两边都是对象则深合并，否则整体替换。
    路径已被校验存在于默认值树；若中间结构被低层整体替换过，
    按「高层说了算」补齐缺失的容器。
    """
    if not segments:
        if isinstance(node, dict) and isinstance(value, dict):
            return deep_merge(node, value)
        return value
    head, rest = segments[0], segments[1:]
    if isinstance(head, int):
        result = list(node) if isinstance(node, list) else []
        if len(result) <= head:
            result.extend([None] * (head + 1 - len(result)))
        result[head] = apply_override(result[head], rest, value)
        return result
    result = dict(node) if isinstance(node, dict) else {}
    result[head] = apply_override(result.get(head), rest, value)
    return result


def apply_flat_layer(tree, parsed_entries):
    """按文件里的键顺序应用一整层扁平覆盖。parsed_entries 是
    [(原始路径, 段元组, 解析后的值), ...]。"""
    for _raw, segments, value in parsed_entries:
        tree = apply_override(tree, segments, value)
    return tree
