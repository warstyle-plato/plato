from setuptools import setup

setup(
    name="developaid-runtime-hotfix",
    version="0.12.36.post1",
    py_modules=[
        "sitecustomize",
        "developaid_runtime_patch",
        "developaid_answer_webapp_patch",
    ],
    description="Compatibility package; runtime source rewriting is disabled",
)
