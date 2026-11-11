"""Read-only comparison of a skill source folder and its installed copy."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat


def is_link(path):
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    return path.is_symlink() or bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def inventory(root):
    if not root.is_dir() or is_link(root) or not (root / "SKILL.md").is_file():
        raise ValueError("skill_directory_required")
    files = {}
    for folder, directories, names in os.walk(root, followlinks=False):
        directories[:] = [name for name in directories if name != "__pycache__"]
        for name in directories + names:
            path = Path(folder) / name
            if is_link(path):
                raise ValueError("linked_entries_not_supported")
        for name in names:
            if name.endswith((".pyc", ".pyo")):
                continue
            path = Path(folder) / name
            if not path.is_file():
                raise ValueError("regular_files_required")
            files[path.relative_to(root).as_posix()] = path
    return files


def compare(source, installed):
    expected, actual = inventory(source), inventory(installed)
    missing = sorted(expected.keys() - actual.keys())
    extra = sorted(actual.keys() - expected.keys())
    changed = sorted(name for name in expected.keys() & actual.keys()
                     if hashlib.sha256(expected[name].read_bytes()).digest()
                     != hashlib.sha256(actual[name].read_bytes()).digest())
    return {"identical": not (missing or extra or changed), "source_files": len(expected),
            "installed_files": len(actual), "missing": missing, "extra": extra, "changed": changed}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("installed", type=Path)
    args = parser.parse_args(argv)
    try:
        result = compare(args.source, args.installed)
    except (OSError, ValueError):
        print(json.dumps({"identical": False, "error": "comparison_unavailable"}))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["identical"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
