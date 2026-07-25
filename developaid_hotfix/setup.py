from __future__ import annotations

import os

from setuptools import setup
from setuptools.command.build_py import build_py


class BuildPyWithPth(build_py):
    """Place the startup hook in wheel purelib so Python processes it on launch."""

    def run(self) -> None:
        super().run()
        self.copy_file(
            "developaid_hotfix.pth",
            os.path.join(self.build_lib, "developaid_hotfix.pth"),
        )


setup(
    name="developaid-runtime-hotfix",
    version="0.12.30",
    py_modules=["developaid_runtime_patch", "sitecustomize"],
    cmdclass={"build_py": BuildPyWithPth},
    description="Runtime patch for DevelopAid Telegram help and Mini App close flow",
)
