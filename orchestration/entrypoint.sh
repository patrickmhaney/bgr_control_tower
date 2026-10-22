#!/usr/bin/env sh
# Dagster in one container: the webserver and the daemon (schedules, sensors).
# Run storage is Postgres (orchestration/dagster.yaml); runs execute in-process,
# which is right at this volume.
set -e
export DAGSTER_HOME="${DAGSTER_HOME:-/app/orchestration}"
dagster-daemon run -m orchestration.definitions &
exec dagster-webserver -h 0.0.0.0 -p 3000 -m orchestration.definitions
