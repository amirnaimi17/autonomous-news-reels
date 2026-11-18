"""Initialize the database using the application command."""

import sys

from app.cli import main

if __name__ == "__main__":
    sys.exit(main(["init-db"]))
