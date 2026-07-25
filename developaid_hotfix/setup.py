from setuptools import setup

setup(
    name="developaid-runtime-hotfix",
    version="0.12.30",
    py_modules=["developaid_runtime_patch"],
    data_files=[("", ["developaid_hotfix.pth"])],
    description="Runtime patch for DevelopAid Telegram help and Mini App close flow",
)
