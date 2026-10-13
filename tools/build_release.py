"""Build the release package of the add-in: a zip holding the add-in folder, ready to unzip into Fusion's add-ins folder or to add from Scripts and Add-Ins.

Only what the add-in needs at run time goes in; tests, docs, tools and the developer's local files are left out. Run from anywhere:

    python tools/build_release.py            # writes dist/<name>-<version>.zip
    python tools/build_release.py --tag v0.1.0   # also fails when the tag differs from the manifest version
"""

import argparse
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "Fusion Manage Item Management"   # Fusion needs the folder, the script and the manifest to share this name
INCLUDE = (f"{NAME}.py", f"{NAME}.manifest", "LICENSE", "README.md", "src", "resources")
SKIP_DIRS = {"__pycache__"}
SKIP_SUFFIXES = {".pyc", ".pyo"}


def manifest_version() -> str:
    return str(json.loads((ROOT / f"{NAME}.manifest").read_text(encoding="utf-8"))["version"])


def files() -> list:
    """Every file to package, in a stable order."""
    found = []
    for entry in INCLUDE:
        path = ROOT / entry
        if not path.exists():
            raise SystemExit(f"Missing from the add-in: {entry}")
        candidates = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
        found += [p for p in candidates if not SKIP_DIRS & set(p.parts) and p.suffix not in SKIP_SUFFIXES]
    return found


def build(out_dir: Path) -> Path:
    version = manifest_version()
    target = out_dir / f"{NAME.replace(' ', '-')}-{version}.zip"
    out_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files():
            archive.write(path, Path(NAME) / path.relative_to(ROOT))
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", help="the release tag (such as v0.1.0), which must match the manifest version")
    parser.add_argument("--out", default=str(ROOT / "dist"), help="where to write the zip")
    args = parser.parse_args()
    if args.tag and args.tag.lstrip("v") != manifest_version():
        raise SystemExit(f"Tag {args.tag} does not match the manifest version {manifest_version()}")
    target = build(Path(args.out))
    print(f"Wrote {target} ({target.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    sys.exit(main())
