"""
Setup script for WordPress Archiver
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read the README file
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text(encoding='utf-8')

setup(
    name="wordpress-archiver",
    version="1.0.0",
    author="WordPress Archiver",
    author_email="",
    description="A comprehensive tool for archiving WordPress content locally using SQLite",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    python_requires=">=3.8",
    install_requires=[
        "requests>=2.25.0",
        "flask>=2.0.0",
        "markupsafe>=2.0.0",
    ],
    extras_require={
        # Video archiving (opt-in --download-videos). Per yt-dlp's official
        # install docs, prefer pip (or the standalone binary) over distro/snap
        # builds, which are third-party and often outdated. Installing here puts
        # yt-dlp in this env, so the archiver runs it as `python -m yt_dlp`
        # (unconfined). A system ffmpeg is also needed to merge >720p streams.
        "video": [
            "yt-dlp[default]",
        ],
        "dev": [
            "pytest>=6.0.0",
            "pytest-cov>=2.0.0",
            "black>=21.0.0",
            "flake8>=3.8.0",
            "mypy>=0.800",
        ],
    },
    entry_points={
        "console_scripts": [
            "wordpress-archiver=wordpress_archiver.main:main",
        ],
    },
    include_package_data=True,
    package_data={
        "wordpress_archiver": [
            "templates/*.html",
            "static/css/*.css",
            "static/js/*.js",
        ],
    },
    keywords="wordpress, archive, backup, sqlite, content-management",
    project_urls={
        "Bug Reports": "",
        "Source": "",
        "Documentation": "",
    },
) 