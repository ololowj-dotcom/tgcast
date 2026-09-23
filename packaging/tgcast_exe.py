import sys
import traceback

from tgcast.cli import main

if __name__ == "__main__":
    try:
        code = main()
    except Exception:
        traceback.print_exc()
        code = 1
        if sys.stdin is not None and sys.stdin.isatty():
            input("\nPress Enter to close this window...")
    sys.exit(code)
