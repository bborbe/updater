"""Entry point for running as a module: python -m updater"""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
