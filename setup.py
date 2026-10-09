from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="ticket-diagnose-agent",
    version="0.1.0",
    description="智能工单诊断与分派 Agent —— ReAct + 并行诊断 Worker + 自动分派",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="tianliuyun",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.9",
    install_requires=[
        "openai>=1.0.0",
    ],
    extras_require={
        "dev": ["pytest>=7.0.0", "pytest-cov>=4.0.0"],
    },
    entry_points={
        "console_scripts": [
            "ticket-diagnose=ticket_diagnose.demo:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)