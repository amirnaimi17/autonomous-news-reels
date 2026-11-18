#!/bin/sh
# Initialize the database, then run the requested command.
# The scheduler command is added in Phase 6. Until then, `status` is the default.

set -eu
python main.py init-db
exec python main.py "$@"
