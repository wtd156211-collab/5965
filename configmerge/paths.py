"""点号路径的解析、校验与规范化。

路径语法：``name[.name]...``，每段名字后可跟若干 ``[数字]`` 下标，
例如 ``server.port``、``pools[1].size``、``matrix[0][1]``。
解析结果是不可变元组，名字段为 str、下标段为 int，可直接当 dict 键做缓存。
"""

from .errors import ConfigError

_NAME_STOP = ".[]"


def parse_path(raw):
    """把路径字符串解析成段元组；语法不合法抛 ``BAD_PATH``。"""
    if not raw:
        raise ConfigError("BAD_PATH", f"path={raw}")
    segments = []
    index = 0
    length = len(raw)
    while True:
        start = index
        while index < length and raw[index] not in _NAME_STOP:
            index += 1
        name = raw[start:index]
        if not name:
            # 空段：路径为空、以点开头/结尾、出现连续两个点
            raise ConfigError("BAD_PATH", f"path={raw}")
        segments.append(name)
        while index < length and raw[index] == "[":
            index += 1
            start = index
            while index < length and raw[index] != "]":
                index += 1
            if index >= length:
                # 方括号没闭合
                raise ConfigError("BAD_PATH", f"path={raw}")
            digits = raw[start:index]
            index += 1
            if not digits or not digits.isascii() or not digits.isdigit():
                # 下标不是数字
                raise ConfigError("BAD_PATH", f"path={raw}")
            segments.append(int(digits))
        if index >= length:
            return tuple(segments)
        if raw[index] == ".":
            index += 1
            if index >= length:
                raise ConfigError("BAD_PATH", f"path={raw}")
            continue
        # 游离的 ']'
        raise ConfigError("BAD_PATH", f"path={raw}")


def canonical(segments):
    """把段元组还原成规范路径串，用于 CYCLE 的 detail。"""
    parts = []
    for seg in segments:
        if isinstance(seg, int):
            parts.append(f"[{seg}]")
        else:
            if parts:
                parts.append(".")
            parts.append(seg)
    return "".join(parts)


def validate_path(segments, defaults, raw):
    """路径的每一段都必须能在默认值树里走通，否则抛 ``UNKNOWN_PATH``。"""
    node = defaults
    for seg in segments:
        if isinstance(seg, int):
            if not isinstance(node, list) or seg >= len(node):
                raise ConfigError("UNKNOWN_PATH", f"path={raw}")
            node = node[seg]
        else:
            if not isinstance(node, dict) or seg not in node:
                raise ConfigError("UNKNOWN_PATH", f"path={raw}")
            node = node[seg]


MISSING = object()


def lookup(tree, segments, default=MISSING):
    """按段元组在树里取值，走不通返回 default。"""
    node = tree
    for seg in segments:
        if isinstance(seg, int):
            if not isinstance(node, list) or seg >= len(node):
                return default
            node = node[seg]
        else:
            if not isinstance(node, dict) or seg not in node:
                return default
            node = node[seg]
    return node
