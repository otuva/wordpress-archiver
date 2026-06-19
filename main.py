#!/usr/bin/env python3
"""
WordPress Archiver - CLI entry point shim.

The CLI implementation lives in the installed package as
``wordpress_archiver.main``. This shim keeps ``python main.py ...`` working
from a source checkout (as documented in the README) without first installing
the package: it puts ``src/`` on the import path so ``wordpress_archiver`` is
importable exactly as it would be once installed.
"""

import os
import sys

# Allow running directly from a source checkout.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from wordpress_archiver.main import main

if __name__ == "__main__":
    main()
