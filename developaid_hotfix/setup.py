from __future__ import annotations

from pathlib import Path

from setuptools import setup


namespace: dict[str, object] = {}
patch_path = Path(__file__).with_name("developaid_runtime_patch.py")
exec(compile(patch_path.read_text(encoding="utf-8"), str(patch_path), "exec"), namespace)
find_main = namespace.get("_find_main_file")
patch_main = namespace.get("_patch_main")
if not callable(find_main) or not callable(patch_main):
    raise RuntimeError("DevelopAid build patch: patch functions not loaded")
main_path = find_main()
if main_path is None:
    raise RuntimeError("DevelopAid build patch: main.py not found")
patch_main(main_path)


setup(
    name="developaid-runtime-hotfix",
    version="0.12.30.post2",
    py_modules=["developaid_runtime_patch"],
    description="Build-time patch for DevelopAid Telegram help and Mini App close flow",
)
