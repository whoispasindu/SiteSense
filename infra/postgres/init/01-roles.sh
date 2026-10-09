#!/bin/sh
# Creates the two SiteSense database roles on first start of the Postgres container.
#
#   sitesense_owner  owns the schema; used only by Alembic migrations
#   sitesense_app    used by the running API; may read and write rows, never change the schema
#
# A bug or injection in the API therefore cannot DROP or ALTER tables.
set -eu

: "${SITESENSE_OWNER_PASSWORD:?must be set}"
: "${SITESENSE_APP_PASSWORD:?must be set}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v owner_pw="$SITESENSE_OWNER_PASSWORD" -v app_pw="$SITESENSE_APP_PASSWORD" <<'SQL'
CREATE ROLE sitesense_owner LOGIN PASSWORD :'owner_pw';
CREATE ROLE sitesense_app LOGIN PASSWORD :'app_pw' NOSUPERUSER NOCREATEDB NOCREATEROLE;
SQL

for db in sitesense sitesense_test; do
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
    -c "CREATE DATABASE $db OWNER sitesense_owner;"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" <<SQL
REVOKE ALL ON DATABASE $db FROM PUBLIC;
GRANT CONNECT ON DATABASE $db TO sitesense_app;
ALTER SCHEMA public OWNER TO sitesense_owner;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO sitesense_app;
ALTER DEFAULT PRIVILEGES FOR ROLE sitesense_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO sitesense_app;
ALTER DEFAULT PRIVILEGES FOR ROLE sitesense_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO sitesense_app;
SQL
done
