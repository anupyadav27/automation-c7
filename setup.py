from setuptools import find_packages, setup

setup(
    name="automation-c7",
    version="0.1.0",
    description="FinOps & Security as Policy engine",
    packages=find_packages(),
    python_requires=">=3.11",
    install_requires=[
        "click>=8.0",
        "pydantic>=2.0",
        "pyyaml>=6.0",
    ],
    extras_require={
        "aws": ["boto3>=1.28"],
        "azure": ["azure-identity>=1.15", "azure-mgmt-resource>=23.0"],
        "gcp": ["google-cloud-asset>=3.0"],
        "dev": ["pytest>=7.0"],
    },
    entry_points={
        "console_scripts": [
            "c7=src.cli:main",
        ],
    },
)
