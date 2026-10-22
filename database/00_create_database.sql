-- SmartSpend: create the application role and database (PostgreSQL 14+).
--
-- Run once as a superuser, for example:
--   psql -U postgres -v app_password=change-me -f database/00_create_database.sql
--
-- Then load the schema into the new database:
--   psql -U smartspend -d smartspend -f database/01_schema.sql
--
-- The Docker Compose setup and `scripts/dev.py` do all of this automatically; these scripts are for a
-- PostgreSQL server you manage yourself.

\if :{?app_password}
\else
  \echo 'Pass the password for the smartspend role: -v app_password=your-password'
  \quit
\endif

-- :'app_password' is psql's safely quoted form; quote_literal quotes it again inside the generated statement.
SELECT 'CREATE ROLE smartspend LOGIN PASSWORD ' || quote_literal(:'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'smartspend')
\gexec

SELECT 'CREATE DATABASE smartspend OWNER smartspend ENCODING ''UTF8'' TEMPLATE template0'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'smartspend')
\gexec

-- The application needs no superuser rights: it owns its database and nothing else.
REVOKE ALL ON DATABASE smartspend FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE smartspend TO smartspend;
