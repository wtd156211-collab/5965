"""引用解析。

在最终合并结果上解析整串 ``${路径}`` 引用：

- 先合并出完整配置树，再遍历树把引用替换为目标「当前位置」的值；
- 支持链式引用，按依赖顺序解析，已解析的路径做记忆化；
- 循环引用报 CYCLE，detail 给出环上路径；
- 目标不存在报 UNKNOWN_REF；以 ``${`` 开头但不是完整引用报 BAD_REF。
"""

from .errors import BAD_REF, CYCLE, UNKNOWN_REF, ConfigError
from .path import parse, to_text


def ref_inner(value):
    """判断字符串是不是引用。

    完整 ``${路径}`` 返回内部路径文本；以 ``${`` 开头但形态不对抛
    BAD_REF；其它情况（含 ``${`` 出现在字符串中间）返回 None。
    """
    if not isinstance(value, str) or not value.startswith("${"):
        return None
    if (value.endswith("}")
            and value.find("}") == len(value) - 1
            and "{" not in value[2:]):
        return value[2:-1]
    raise ConfigError(BAD_REF, f"value={value}")


class _Resolver:
    """按路径解析目标值，带链式解析、记忆化与环检测。"""

    def __init__(self, root):
        self._root = root
        self._resolved = {}
        self._active = set()
        self._stack = []

    def _lookup(self, segments, ref_text):
        node = self._root
        for segment in segments:
            if isinstance(segment, int):
                if not isinstance(node, list) or segment >= len(node):
                    raise ConfigError(UNKNOWN_REF, f"ref={ref_text}")
                node = node[segment]
            else:
                if not isinstance(node, dict) or segment not in node:
                    raise ConfigError(UNKNOWN_REF, f"ref={ref_text}")
                node = node[segment]
        return node

    def _cycle_error(self, segments):
        displays = [display for _, display in self._stack]
        start = next(i for i, (seg, _) in enumerate(self._stack)
                     if seg == segments)
        cycle = displays[start:]
        # 环的起点取最小路径的后继，结尾再回到它
        least = min(cycle)
        index = cycle.index(least)
        rotated = cycle[index + 1:] + cycle[:index + 1]
        raise ConfigError(CYCLE, "->".join(rotated + [rotated[0]]))

    def resolve_path(self, segments, ref_text):
        if segments in self._resolved:
            return self._resolved[segments]
        if segments in self._active:
            self._cycle_error(segments)

        self._active.add(segments)
        self._stack.append((segments, to_text(segments)))
        value = self._lookup(segments, ref_text)
        inner = ref_inner(value)
        if inner is not None:
            value = self.resolve_ref(inner)
        self._stack.pop()
        self._active.discard(segments)
        self._resolved[segments] = value
        return value

    def resolve_ref(self, ref_text):
        try:
            segments = parse(ref_text)
        except ConfigError:
            raise ConfigError(UNKNOWN_REF, f"ref={ref_text}")
        return self.resolve_path(segments, ref_text)


def resolve_refs(output):
    """就地解析结果树上的所有引用，返回同一棵树。"""
    resolver = _Resolver(output)

    def visit(container):
        if isinstance(container, dict):
            for key in container.keys():
                value = container[key]
                inner = ref_inner(value)
                if inner is not None:
                    container[key] = resolver.resolve_ref(inner)
                else:
                    visit(value)
        elif isinstance(container, list):
            for index, value in enumerate(container):
                inner = ref_inner(value)
                if inner is not None:
                    container[index] = resolver.resolve_ref(inner)
                else:
                    visit(value)

    visit(output)
    return output
