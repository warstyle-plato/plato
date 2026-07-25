from setuptools import setup

setup(
    name="developaid-runtime-hotfix",
    version="0.12.32",
    py_modules=[
        "sitecustomize",
        "developaid_runtime_patch",
        "developaid_answer_webapp_patch",
    ],
    description="DevelopAid Telegram help and server-side Mini App close patches",
)
