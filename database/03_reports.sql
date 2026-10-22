-- SmartSpend: read-only admin queries. Nothing here changes data.
--
--   psql -d smartspend -f database/03_reports.sql
--   psql -d smartspend -v workspace="'<workspace uuid>'" -f database/03_reports.sql
--
-- Spending follows the app's rules: only active transactions count, an expense counts its
-- effective_amount (the part not already counted through a linked bill), and refunds are subtracted.
-- Merged duplicates (status = 'merged') never count.

\if :{?workspace}
\else
  \set workspace NULL
\endif

\echo '== Workspaces (households in the database) and their members'
SELECT h.id, h.name, h.base_currency, h.is_demo, count(m.id) AS members, h.created_at::date AS created
  FROM households h
  LEFT JOIN household_members m ON m.household_id = h.id
 WHERE :workspace::uuid IS NULL OR h.id = :workspace::uuid
 GROUP BY h.id
 ORDER BY h.created_at DESC
 LIMIT 50;

\echo '== Net spending by month (last 12 months)'
SELECT h.name AS workspace,
       to_char(date_trunc('month', t.occurred_on), 'YYYY-MM') AS month,
       sum(CASE WHEN t.type = 'expense' THEN t.effective_amount ELSE 0 END)
     - sum(CASE WHEN t.type = 'refund' THEN t.effective_amount ELSE 0 END) AS net_spending,
       sum(CASE WHEN t.type = 'income' THEN t.effective_amount ELSE 0 END) AS income,
       t.currency
  FROM canonical_transactions t
  JOIN households h ON h.id = t.household_id
 WHERE t.status = 'active'
   AND t.occurred_on >= date_trunc('month', current_date) - interval '11 months'
   AND (:workspace::uuid IS NULL OR t.household_id = :workspace::uuid)
 GROUP BY h.name, month, t.currency
 ORDER BY h.name, month;

\echo '== Matches waiting for review'
SELECT h.name AS workspace, r.kind, r.confidence, count(*) AS suggestions
  FROM reconciliation_matches r
  JOIN households h ON h.id = r.household_id
 WHERE r.status = 'suggested'
   AND (:workspace::uuid IS NULL OR r.household_id = :workspace::uuid)
 GROUP BY h.name, r.kind, r.confidence
 ORDER BY h.name, suggestions DESC;

\echo '== Uploaded documents by status'
SELECT h.name AS workspace, d.status, count(*) AS documents, pg_size_pretty(sum(d.size_bytes)) AS total_size
  FROM documents d
  JOIN households h ON h.id = d.household_id
 WHERE :workspace::uuid IS NULL OR d.household_id = :workspace::uuid
 GROUP BY h.name, d.status
 ORDER BY h.name, documents DESC;

\echo '== Credit card bills due in the next 14 days'
SELECT h.name AS workspace, a.name AS card, s.statement_date, s.due_date, s.total_due, s.minimum_due, s.currency
  FROM credit_card_statements s
  JOIN accounts a ON a.id = s.account_id
  JOIN households h ON h.id = s.household_id
 WHERE s.due_date BETWEEN current_date AND current_date + 14
   AND (:workspace::uuid IS NULL OR s.household_id = :workspace::uuid)
 ORDER BY s.due_date;

\echo '== Integrity: transactions merged into a record that is not active (should be empty)'
SELECT t.id, t.household_id, t.merged_into_id
  FROM canonical_transactions t
  JOIN canonical_transactions target ON target.id = t.merged_into_id
 WHERE t.status = 'merged' AND target.status <> 'active';

\echo '== Table sizes'
SELECT relname AS table_name, n_live_tup AS approx_rows, pg_size_pretty(pg_total_relation_size(relid)) AS size
  FROM pg_stat_user_tables
 ORDER BY pg_total_relation_size(relid) DESC
 LIMIT 15;
