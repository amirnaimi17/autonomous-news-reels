#!/usr/bin/env python
"""Django admin for the single project database."""

import os
import sys
from pathlib import Path


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "studio.settings")
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
