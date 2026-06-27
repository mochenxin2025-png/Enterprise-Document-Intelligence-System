from setuptools import setup, find_packages

setup(
    name="edis",
    version="1.0.0",
    description="Enterprise Document Intelligence System — Agent-First Engineering Document Intelligence Framework",
    long_description=open("README.md", encoding="utf-8").read() if __import__("os").path.exists("README.md") else "",
    author="EDIS Team",
    packages=find_packages(exclude=["tests", "data"]),
    python_requires=">=3.10",
    install_requires=[
        "httpx>=0.24",
        "pymupdf>=1.23",
        "sqlite-vec>=0.1",
        "numpy>=1.24",
        "torch>=2.0",
        "transformers>=4.40",
        "pyyaml>=6.0",
        "chardet>=5.0",
        "pytest>=7.0",
    ],
    extras_require={
        "ocr": ["paddleocr>=3.0"],
        "all": ["paddleocr>=3.0"],
    },
    entry_points={
        "console_scripts": [
            "edis = main:main",  # CLI 入口
        ],
        "edis.extensions": [
            # 第三方扩展通过此 entry_point 注册
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Scientific/Engineering",
    ],
)
