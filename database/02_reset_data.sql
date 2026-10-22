-- SmartSpend: DELETE ALL DATA but keep the schema. Development and test databases only.
--
--   psql -d smartspend -v confirm=yes -f database/02_reset_data.sql
--
-- Every user, workspace, transaction, document record and audit entry is removed. Uploaded files in
-- storage (backend/var/storage or S3) are not touched; delete them separately if needed.
-- The migration version (alembic_version) is kept, so the app starts normally afterwards.

\if :{?confirm}
\else
  \echo 'This deletes all data. Re-run with -v confirm=yes to proceed.'
  \quit
\endif

DO $$
DECLARE
  tables text;
BEGIN
  SELECT string_agg(format('%I.%I', schemaname, tablename), ', ')
    INTO tables
    FROM pg_tables
   WHERE schemaname = 'public' AND tablename <> 'alembic_version';
  IF tables IS NOT NULL THEN
    EXECUTE 'TRUNCATE TABLE ' || tables || ' RESTART IDENTITY CASCADE';
  END IF;
END $$;

SELECT 'All SmartSpend data deleted' AS result;
