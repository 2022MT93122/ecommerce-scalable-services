#!/bin/sh
set -eu
for name in inventory order payment notification; do
  psql -v ON_ERROR_STOP=1 -U postgres <<SQL
CREATE USER ${name}_user WITH PASSWORD '${name}_pass';
CREATE DATABASE ${name}_db OWNER ${name}_user;
SQL
done
