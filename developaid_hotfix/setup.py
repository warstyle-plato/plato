from __future__ import annotations

from setuptools import setup

import developaid_runtime_patch as hotfix


main_path = hotfix._find_main_file()
if main_path is None:
    raise RuntimeError("DevelopAid build patch: main.py not found")
hotfix._patch_main(main_path)


setup(
    name="developaid-runtime-hotfix",
    version="0.12.30.post1",
    py_modules=["developaid_runtime_patch"],
    description="Build-time patch for DevelopAid Telegram help and Mini App close flow",
)
