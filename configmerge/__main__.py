"""命令行入口：python -m configmerge <用例目录>"""

import sys

from . import run_dir


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: python -m configmerge <case-dir>", file=sys.stderr)
        return 2
    text, ok = run_dir(argv[0])
    sys.stdout.write(text)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
