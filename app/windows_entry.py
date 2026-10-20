"""Portable runtime entrypoint."""
import os
from pathlib import Path
import runpy
import sys
from dotenv import load_dotenv
ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
load_dotenv(ROOT / ".env", override=True)
os.environ.setdefault("HF_HOME", str(ROOT.parent / "runtime/model-cache"))
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
if sys.platform == "win32":
    import winloop
    winloop.install()
if __name__ == "__main__":
    target = (ROOT / sys.argv[1]).resolve()
    if not target.is_relative_to(ROOT) or not target.is_file():
        raise SystemExit("Invalid entrypoint")
    sys.argv = [str(target), *sys.argv[2:]]
    runpy.run_path(str(target), run_name="__main__")
