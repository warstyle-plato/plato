from setuptools import setup

setup(
    name="developaid-runtime-hotfix",
    version="0.12.36",
    py_modules=[
        "sitecustomize",
        "developaid_runtime_patch",
        "developaid_answer_webapp_patch",
    ],
    description="Compatibility package; Telegram Platon advisor is loaded by the main package",
)
