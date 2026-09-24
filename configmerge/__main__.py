"""命令行入口：python -m configmerge <case-dir>"""

import sys

from . import run_case


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m configmerge <case-dir>", file=sys.stderr)
        return 2
    try:
        sys.stdout.write(run_case(args[0]))
    except (OSError, ValueError) as exc:
        print(f"configmerge: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
