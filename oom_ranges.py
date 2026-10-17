#!/usr/bin/env python3
"""Finds, for every Java heap size, the row count where the test starts to fail with a Java heap OOM.

    ./oom_ranges.py [--plan] [options]      (--help describes the search and the options)

The code is in the oom package: see oom/cli.py.
"""
import sys

from oom.cli import main

if __name__ == "__main__":
    sys.exit(main())
