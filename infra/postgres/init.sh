#!/bin/sh
set -eu
psql --username "$POSTGRES_USER" --dbname postgres --set=ON_ERROR_STOP=1 \
  --set=owner_password="$PIPEGUARD_OWNER_PASSWORD" <<'SQL'
CREATE ROLE pipeguard_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'owner_password';
CREATE DATABASE pipeguard OWNER pipeguard_owner;
REVOKE ALL ON DATABASE pipeguard FROM PUBLIC;
SQL
