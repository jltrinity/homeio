#!/bin/sh
set -eu
umask 077
python -m homeio.cli init
exec "$@"
