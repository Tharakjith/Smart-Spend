-- SmartSpend: complete database schema (PostgreSQL 14+), generated from the Alembic migrations.
-- Do not edit by hand: change a migration, then run  database/scripts/db.sh schema
-- Load into an empty database:  psql -d smartspend -v ON_ERROR_STOP=1 -f database/01_schema.sql
-- Generated 2026-10-22 13:40

BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 5fe15cd05018

CREATE TABLE households (
    name VARCHAR(200) NOT NULL, 
    base_currency VARCHAR(3) NOT NULL, 
    timezone VARCHAR(64) NOT NULL, 
    ai_opt_in BOOLEAN NOT NULL, 
    matching_config JSONB NOT NULL, 
    is_demo BOOLEAN NOT NULL, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_households PRIMARY KEY (id)
);

CREATE TABLE users (
    email VARCHAR(320) NOT NULL, 
    password_hash VARCHAR(255) NOT NULL, 
    full_name VARCHAR(200) NOT NULL, 
    email_verified_at TIMESTAMP WITH TIME ZONE, 
    mfa_enabled BOOLEAN NOT NULL, 
    mfa_secret_enc TEXT, 
    is_active BOOLEAN NOT NULL, 
    failed_login_count INTEGER NOT NULL, 
    locked_until TIMESTAMP WITH TIME ZONE, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_users PRIMARY KEY (id)
);

CREATE UNIQUE INDEX uq_users_email_lower ON users (lower(email));

CREATE TABLE accounts (
    household_id UUID NOT NULL, 
    name VARCHAR(120) NOT NULL, 
    type VARCHAR(20) NOT NULL, 
    currency VARCHAR(3) NOT NULL, 
    opening_balance NUMERIC(19, 4) NOT NULL, 
    opening_balance_date DATE, 
    institution VARCHAR(120) NOT NULL, 
    masked_number VARCHAR(8) NOT NULL, 
    upi_handle VARCHAR(120) NOT NULL, 
    is_archived BOOLEAN NOT NULL, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_accounts PRIMARY KEY (id), 
    CONSTRAINT ck_accounts_type_valid CHECK (type in ('cash','bank','upi','debit_card','credit_card','wallet','other')), 
    CONSTRAINT fk_accounts_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE, 
    CONSTRAINT uq_accounts_household_id_name UNIQUE (household_id, name)
);

CREATE INDEX ix_accounts_household_id ON accounts (household_id);

CREATE TABLE audit_logs (
    household_id UUID, 
    actor_id UUID, 
    action VARCHAR(64) NOT NULL, 
    entity_type VARCHAR(64) NOT NULL, 
    entity_id VARCHAR(64), 
    before JSONB, 
    after JSONB, 
    ip VARCHAR(64) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id UUID NOT NULL, 
    CONSTRAINT pk_audit_logs PRIMARY KEY (id), 
    CONSTRAINT fk_audit_logs_actor_id_users FOREIGN KEY(actor_id) REFERENCES users (id) ON DELETE SET NULL, 
    CONSTRAINT fk_audit_logs_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE
);

CREATE INDEX ix_audit_logs_created_at ON audit_logs (created_at);

CREATE INDEX ix_audit_logs_entity_id ON audit_logs (entity_id);

CREATE INDEX ix_audit_logs_household_id ON audit_logs (household_id);

CREATE TABLE categories (
    household_id UUID NOT NULL, 
    parent_id UUID, 
    name VARCHAR(120) NOT NULL, 
    kind VARCHAR(16) NOT NULL, 
    is_system BOOLEAN NOT NULL, 
    is_fixed BOOLEAN NOT NULL, 
    color VARCHAR(16) NOT NULL, 
    icon VARCHAR(40) NOT NULL, 
    is_archived BOOLEAN NOT NULL, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_categories PRIMARY KEY (id), 
    CONSTRAINT fk_categories_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE, 
    CONSTRAINT fk_categories_parent_id_categories FOREIGN KEY(parent_id) REFERENCES categories (id) ON DELETE CASCADE
);

CREATE INDEX ix_categories_household_id ON categories (household_id);

CREATE UNIQUE INDEX uq_categories_sibling_name ON categories (household_id, parent_id, name) NULLS NOT DISTINCT;

CREATE TABLE counterparties (
    household_id UUID NOT NULL, 
    name VARCHAR(200) NOT NULL, 
    email VARCHAR(320) NOT NULL, 
    phone VARCHAR(40) NOT NULL, 
    upi_id VARCHAR(120) NOT NULL, 
    notes TEXT NOT NULL, 
    is_archived BOOLEAN NOT NULL, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_counterparties PRIMARY KEY (id), 
    CONSTRAINT fk_counterparties_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE, 
    CONSTRAINT uq_counterparties_household_id_name UNIQUE (household_id, name)
);

CREATE INDEX ix_counterparties_household_id ON counterparties (household_id);

CREATE TABLE documents (
    household_id UUID NOT NULL, 
    uploaded_by UUID, 
    original_filename VARCHAR(255) NOT NULL, 
    content_type VARCHAR(100) NOT NULL, 
    size_bytes INTEGER NOT NULL, 
    sha256 VARCHAR(64) NOT NULL, 
    storage_key VARCHAR(300) NOT NULL, 
    status VARCHAR(16) NOT NULL, 
    doc_kind VARCHAR(20) NOT NULL, 
    page_count INTEGER, 
    error_message TEXT NOT NULL, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_documents PRIMARY KEY (id), 
    CONSTRAINT ck_documents_status_valid CHECK (status in ('uploaded','queued','processing','needs_review','confirmed','failed','archived')), 
    CONSTRAINT fk_documents_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE, 
    CONSTRAINT fk_documents_uploaded_by_users FOREIGN KEY(uploaded_by) REFERENCES users (id) ON DELETE SET NULL, 
    CONSTRAINT uq_documents_household_id_sha256 UNIQUE (household_id, sha256)
);

CREATE INDEX ix_documents_household_id ON documents (household_id);

CREATE TABLE email_tokens (
    user_id UUID NOT NULL, 
    purpose VARCHAR(32) NOT NULL, 
    token_hash VARCHAR(128) NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    used_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id UUID NOT NULL, 
    CONSTRAINT pk_email_tokens PRIMARY KEY (id), 
    CONSTRAINT fk_email_tokens_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_email_tokens_token_hash UNIQUE (token_hash)
);

CREATE INDEX ix_email_tokens_user_id ON email_tokens (user_id);

CREATE TABLE household_members (
    household_id UUID NOT NULL, 
    user_id UUID NOT NULL, 
    role VARCHAR(16) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id UUID NOT NULL, 
    CONSTRAINT pk_household_members PRIMARY KEY (id), 
    CONSTRAINT ck_household_members_role_valid CHECK (role in ('owner','admin','member','viewer')), 
    CONSTRAINT fk_household_members_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE, 
    CONSTRAINT fk_household_members_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_household_members_household_id_user_id UNIQUE (household_id, user_id)
);

CREATE INDEX ix_household_members_user_id ON household_members (user_id);

CREATE TABLE idempotency_keys (
    household_id UUID NOT NULL, 
    user_id UUID NOT NULL, 
    key VARCHAR(128) NOT NULL, 
    method VARCHAR(8) NOT NULL, 
    path VARCHAR(400) NOT NULL, 
    request_hash VARCHAR(64) NOT NULL, 
    response_status INTEGER, 
    response_body JSONB, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id UUID NOT NULL, 
    CONSTRAINT pk_idempotency_keys PRIMARY KEY (id), 
    CONSTRAINT fk_idempotency_keys_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE, 
    CONSTRAINT fk_idempotency_keys_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_idempotency_keys_household_id_key UNIQUE (household_id, key)
);

CREATE TABLE notifications (
    household_id UUID NOT NULL, 
    user_id UUID, 
    kind VARCHAR(40) NOT NULL, 
    severity VARCHAR(10) NOT NULL, 
    title VARCHAR(200) NOT NULL, 
    body TEXT NOT NULL, 
    link VARCHAR(300) NOT NULL, 
    dedupe_key VARCHAR(200) NOT NULL, 
    read_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id UUID NOT NULL, 
    CONSTRAINT pk_notifications PRIMARY KEY (id), 
    CONSTRAINT fk_notifications_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE, 
    CONSTRAINT fk_notifications_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_notifications_household_id_dedupe_key UNIQUE (household_id, dedupe_key)
);

CREATE INDEX ix_notifications_created_at ON notifications (created_at);

CREATE INDEX ix_notifications_household_id ON notifications (household_id);

CREATE TABLE savings_goals (
    household_id UUID NOT NULL, 
    name VARCHAR(120) NOT NULL, 
    target_amount NUMERIC(19, 4) NOT NULL, 
    saved_amount NUMERIC(19, 4) NOT NULL, 
    currency VARCHAR(3) NOT NULL, 
    target_date DATE, 
    status VARCHAR(12) NOT NULL, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_savings_goals PRIMARY KEY (id), 
    CONSTRAINT ck_savings_goals_amounts_valid CHECK (target_amount > 0 and saved_amount >= 0), 
    CONSTRAINT fk_savings_goals_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE
);

CREATE INDEX ix_savings_goals_household_id ON savings_goals (household_id);

CREATE TABLE user_sessions (
    user_id UUID NOT NULL, 
    refresh_token_hash VARCHAR(128) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    last_used_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    revoked_at TIMESTAMP WITH TIME ZONE, 
    user_agent VARCHAR(400) NOT NULL, 
    ip VARCHAR(64) NOT NULL, 
    id UUID NOT NULL, 
    CONSTRAINT pk_user_sessions PRIMARY KEY (id), 
    CONSTRAINT fk_user_sessions_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_user_sessions_refresh_token_hash UNIQUE (refresh_token_hash)
);

CREATE INDEX ix_user_sessions_user_id ON user_sessions (user_id);

CREATE TABLE budgets (
    household_id UUID NOT NULL, 
    name VARCHAR(120) NOT NULL, 
    period VARCHAR(10) NOT NULL, 
    category_id UUID, 
    amount NUMERIC(19, 4) NOT NULL, 
    currency VARCHAR(3) NOT NULL, 
    alert_threshold_pct INTEGER NOT NULL, 
    is_active BOOLEAN NOT NULL, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_budgets PRIMARY KEY (id), 
    CONSTRAINT ck_budgets_period_valid CHECK (period in ('monthly','weekly')), 
    CONSTRAINT ck_budgets_threshold_valid CHECK (alert_threshold_pct between 1 and 100), 
    CONSTRAINT ck_budgets_amount_positive CHECK (amount > 0), 
    CONSTRAINT fk_budgets_category_id_categories FOREIGN KEY(category_id) REFERENCES categories (id) ON DELETE CASCADE, 
    CONSTRAINT fk_budgets_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE
);

CREATE INDEX ix_budgets_household_id ON budgets (household_id);

CREATE TABLE document_processing_jobs (
    household_id UUID NOT NULL, 
    document_id UUID NOT NULL, 
    job_type VARCHAR(20) NOT NULL, 
    status VARCHAR(16) NOT NULL, 
    attempts INTEGER NOT NULL, 
    max_attempts INTEGER NOT NULL, 
    last_error TEXT NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    started_at TIMESTAMP WITH TIME ZONE, 
    finished_at TIMESTAMP WITH TIME ZONE, 
    id UUID NOT NULL, 
    CONSTRAINT pk_document_processing_jobs PRIMARY KEY (id), 
    CONSTRAINT fk_document_processing_jobs_document_id_documents FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE, 
    CONSTRAINT fk_document_processing_jobs_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE
);

CREATE INDEX ix_document_processing_jobs_document_id ON document_processing_jobs (document_id);

CREATE TABLE merchants (
    household_id UUID NOT NULL, 
    name VARCHAR(200) NOT NULL, 
    normalized_name VARCHAR(200) NOT NULL, 
    default_category_id UUID, 
    upi_id VARCHAR(120) NOT NULL, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_merchants PRIMARY KEY (id), 
    CONSTRAINT fk_merchants_default_category_id_categories FOREIGN KEY(default_category_id) REFERENCES categories (id) ON DELETE SET NULL, 
    CONSTRAINT fk_merchants_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE, 
    CONSTRAINT uq_merchants_household_id_normalized_name UNIQUE (household_id, normalized_name)
);

CREATE INDEX ix_merchants_household_id ON merchants (household_id);

CREATE TABLE statement_imports (
    household_id UUID NOT NULL, 
    account_id UUID, 
    uploaded_by UUID, 
    original_filename VARCHAR(255) NOT NULL, 
    sha256 VARCHAR(64) NOT NULL, 
    storage_key VARCHAR(300) NOT NULL, 
    file_format VARCHAR(8) NOT NULL, 
    source_kind VARCHAR(20) NOT NULL, 
    currency VARCHAR(3) NOT NULL, 
    date_format VARCHAR(20), 
    status VARCHAR(16) NOT NULL, 
    headers JSONB NOT NULL, 
    raw_rows JSONB NOT NULL, 
    column_mapping JSONB NOT NULL, 
    row_count INTEGER NOT NULL, 
    imported_count INTEGER NOT NULL, 
    skipped_duplicates INTEGER NOT NULL, 
    invalid_count INTEGER NOT NULL, 
    error_message TEXT NOT NULL, 
    confirmed_at TIMESTAMP WITH TIME ZONE, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_statement_imports PRIMARY KEY (id), 
    CONSTRAINT fk_statement_imports_account_id_accounts FOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE SET NULL, 
    CONSTRAINT fk_statement_imports_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE, 
    CONSTRAINT fk_statement_imports_uploaded_by_users FOREIGN KEY(uploaded_by) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_statement_imports_household_id ON statement_imports (household_id);

CREATE TABLE user_rules (
    household_id UUID NOT NULL, 
    name VARCHAR(120) NOT NULL, 
    priority INTEGER NOT NULL, 
    field VARCHAR(20) NOT NULL, 
    operator VARCHAR(20) NOT NULL, 
    pattern VARCHAR(300) NOT NULL, 
    category_id UUID, 
    set_type VARCHAR(32), 
    is_active BOOLEAN NOT NULL, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_user_rules PRIMARY KEY (id), 
    CONSTRAINT ck_user_rules_field_valid CHECK (field in ('description','merchant','item','counterparty')), 
    CONSTRAINT ck_user_rules_operator_valid CHECK (operator in ('contains','equals','starts_with','regex')), 
    CONSTRAINT ck_user_rules_has_effect CHECK (category_id is not null or set_type is not null), 
    CONSTRAINT fk_user_rules_category_id_categories FOREIGN KEY(category_id) REFERENCES categories (id) ON DELETE CASCADE, 
    CONSTRAINT fk_user_rules_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE
);

CREATE INDEX ix_user_rules_household_id ON user_rules (household_id);

CREATE TABLE canonical_transactions (
    household_id UUID NOT NULL, 
    created_by UUID, 
    type VARCHAR(32) NOT NULL, 
    occurred_on DATE NOT NULL, 
    occurred_at TIMESTAMP WITH TIME ZONE, 
    description VARCHAR(500) NOT NULL, 
    amount NUMERIC(19, 4) NOT NULL, 
    effective_amount NUMERIC(19, 4) NOT NULL, 
    cash_amount NUMERIC(19, 4) NOT NULL, 
    currency VARCHAR(3) NOT NULL, 
    category_id UUID, 
    category_source VARCHAR(20) NOT NULL, 
    merchant_id UUID, 
    counterparty_id UUID, 
    account_id UUID, 
    to_account_id UUID, 
    payment_method VARCHAR(20), 
    notes TEXT NOT NULL, 
    tags JSONB NOT NULL, 
    status VARCHAR(16) NOT NULL, 
    merged_into_id UUID, 
    related_transaction_id UUID, 
    reconciliation_status VARCHAR(24) NOT NULL, 
    review_status VARCHAR(16) NOT NULL, 
    is_recurring BOOLEAN NOT NULL, 
    version INTEGER NOT NULL, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_canonical_transactions PRIMARY KEY (id), 
    CONSTRAINT ck_canonical_transactions_recon_valid CHECK (reconciliation_status in ('unmatched','suggested_match','matched','partially_paid','fully_paid','partially_reconciled','needs_review','disputed','reversed')), 
    CONSTRAINT ck_canonical_transactions_merged_has_target CHECK (status <> 'merged' or merged_into_id is not null), 
    CONSTRAINT ck_canonical_transactions_status_valid CHECK (status in ('active','voided','merged','reversed')), 
    CONSTRAINT ck_canonical_transactions_type_valid CHECK (type in ('expense','income','transfer','refund','loan_given','loan_received','loan_repayment_paid','loan_repayment_received','reimbursement_paid','reimbursement_received','credit_card_payment')), 
    CONSTRAINT ck_canonical_transactions_amount_nonneg CHECK (amount >= 0), 
    CONSTRAINT ck_canonical_transactions_cash_bounds CHECK (cash_amount >= 0 and cash_amount <= amount), 
    CONSTRAINT ck_canonical_transactions_effective_bounds CHECK (effective_amount >= 0 and effective_amount <= amount), 
    CONSTRAINT fk_canonical_transactions_account_id_accounts FOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE SET NULL, 
    CONSTRAINT fk_canonical_transactions_category_id_categories FOREIGN KEY(category_id) REFERENCES categories (id) ON DELETE SET NULL, 
    CONSTRAINT fk_canonical_transactions_counterparty_id_counterparties FOREIGN KEY(counterparty_id) REFERENCES counterparties (id) ON DELETE SET NULL, 
    CONSTRAINT fk_canonical_transactions_created_by_users FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL, 
    CONSTRAINT fk_canonical_transactions_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE, 
    CONSTRAINT fk_canonical_transactions_merchant_id_merchants FOREIGN KEY(merchant_id) REFERENCES merchants (id) ON DELETE SET NULL, 
    CONSTRAINT fk_canonical_transactions_merged_into_id_canonical_transactions FOREIGN KEY(merged_into_id) REFERENCES canonical_transactions (id) ON DELETE SET NULL, 
    CONSTRAINT fk_canonical_transactions_related_transaction_id_canoni_d358 FOREIGN KEY(related_transaction_id) REFERENCES canonical_transactions (id) ON DELETE SET NULL, 
    CONSTRAINT fk_canonical_transactions_to_account_id_accounts FOREIGN KEY(to_account_id) REFERENCES accounts (id) ON DELETE SET NULL
);

CREATE INDEX ix_canonical_transactions_account_id ON canonical_transactions (account_id);

CREATE INDEX ix_canonical_transactions_category_id ON canonical_transactions (category_id);

CREATE INDEX ix_canonical_transactions_counterparty_id ON canonical_transactions (counterparty_id);

CREATE INDEX ix_canonical_transactions_merchant_id ON canonical_transactions (merchant_id);

CREATE INDEX ix_ctx_household_date ON canonical_transactions (household_id, occurred_on);

CREATE INDEX ix_ctx_household_type_status ON canonical_transactions (household_id, type, status);

CREATE TABLE merchant_aliases (
    household_id UUID NOT NULL, 
    merchant_id UUID NOT NULL, 
    alias VARCHAR(200) NOT NULL, 
    normalized_alias VARCHAR(200) NOT NULL, 
    source VARCHAR(20) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    id UUID NOT NULL, 
    CONSTRAINT pk_merchant_aliases PRIMARY KEY (id), 
    CONSTRAINT fk_merchant_aliases_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE, 
    CONSTRAINT fk_merchant_aliases_merchant_id_merchants FOREIGN KEY(merchant_id) REFERENCES merchants (id) ON DELETE CASCADE, 
    CONSTRAINT uq_merchant_aliases_household_id_normalized_alias UNIQUE (household_id, normalized_alias)
);

CREATE INDEX ix_merchant_aliases_merchant_id ON merchant_aliases (merchant_id);

CREATE TABLE statement_rows (
    household_id UUID NOT NULL, 
    import_id UUID NOT NULL, 
    account_id UUID, 
    row_index INTEGER NOT NULL, 
    raw JSONB NOT NULL, 
    occurred_on DATE NOT NULL, 
    description VARCHAR(500) NOT NULL, 
    amount NUMERIC(19, 4) NOT NULL, 
    direction VARCHAR(4) NOT NULL, 
    currency VARCHAR(3) NOT NULL, 
    reference VARCHAR(64), 
    balance NUMERIC(19, 4), 
    fingerprint VARCHAR(64) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id UUID NOT NULL, 
    CONSTRAINT pk_statement_rows PRIMARY KEY (id), 
    CONSTRAINT ck_statement_rows_amount_nonneg CHECK (amount >= 0), 
    CONSTRAINT fk_statement_rows_account_id_accounts FOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE SET NULL, 
    CONSTRAINT fk_statement_rows_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE, 
    CONSTRAINT fk_statement_rows_import_id_statement_imports FOREIGN KEY(import_id) REFERENCES statement_imports (id) ON DELETE CASCADE, 
    CONSTRAINT uq_statement_rows_household_id_fingerprint UNIQUE (household_id, fingerprint)
);

CREATE INDEX ix_statement_rows_import_id ON statement_rows (import_id);

CREATE TABLE duplicate_candidates (
    household_id UUID NOT NULL, 
    kind VARCHAR(20) NOT NULL, 
    existing_document_id UUID, 
    existing_statement_row_id UUID, 
    import_id UUID, 
    attempted_filename VARCHAR(255) NOT NULL, 
    details JSONB NOT NULL, 
    status VARCHAR(10) NOT NULL, 
    detected_by UUID, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id UUID NOT NULL, 
    CONSTRAINT pk_duplicate_candidates PRIMARY KEY (id), 
    CONSTRAINT fk_duplicate_candidates_detected_by_users FOREIGN KEY(detected_by) REFERENCES users (id) ON DELETE SET NULL, 
    CONSTRAINT fk_duplicate_candidates_existing_document_id_documents FOREIGN KEY(existing_document_id) REFERENCES documents (id) ON DELETE CASCADE, 
    CONSTRAINT fk_duplicate_candidates_existing_statement_row_id_state_67ae FOREIGN KEY(existing_statement_row_id) REFERENCES statement_rows (id) ON DELETE CASCADE, 
    CONSTRAINT fk_duplicate_candidates_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE, 
    CONSTRAINT fk_duplicate_candidates_import_id_statement_imports FOREIGN KEY(import_id) REFERENCES statement_imports (id) ON DELETE CASCADE
);

CREATE INDEX ix_duplicate_candidates_household_id ON duplicate_candidates (household_id);

CREATE TABLE extracted_documents (
    household_id UUID NOT NULL, 
    document_id UUID NOT NULL, 
    method VARCHAR(20) NOT NULL, 
    raw_text TEXT NOT NULL, 
    fields JSONB NOT NULL, 
    line_items JSONB NOT NULL, 
    validation JSONB NOT NULL, 
    overall_confidence NUMERIC(4, 3) NOT NULL, 
    suggested_category_id UUID, 
    suggested_merchant_id UUID, 
    transaction_id UUID, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_extracted_documents PRIMARY KEY (id), 
    CONSTRAINT fk_extracted_documents_document_id_documents FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE, 
    CONSTRAINT fk_extracted_documents_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE, 
    CONSTRAINT fk_extracted_documents_suggested_category_id_categories FOREIGN KEY(suggested_category_id) REFERENCES categories (id) ON DELETE SET NULL, 
    CONSTRAINT fk_extracted_documents_suggested_merchant_id_merchants FOREIGN KEY(suggested_merchant_id) REFERENCES merchants (id) ON DELETE SET NULL, 
    CONSTRAINT fk_extracted_documents_transaction_id_canonical_transactions FOREIGN KEY(transaction_id) REFERENCES canonical_transactions (id) ON DELETE SET NULL, 
    CONSTRAINT uq_extracted_documents_document_id UNIQUE (document_id)
);

CREATE TABLE loans (
    household_id UUID NOT NULL, 
    counterparty_id UUID NOT NULL, 
    direction VARCHAR(10) NOT NULL, 
    principal NUMERIC(19, 4) NOT NULL, 
    currency VARCHAR(3) NOT NULL, 
    interest_rate_pct NUMERIC(7, 4), 
    start_date DATE NOT NULL, 
    due_date DATE, 
    status VARCHAR(12) NOT NULL, 
    notes TEXT NOT NULL, 
    account_id UUID, 
    transaction_id UUID, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_loans PRIMARY KEY (id), 
    CONSTRAINT ck_loans_direction_valid CHECK (direction in ('given','received')), 
    CONSTRAINT ck_loans_principal_positive CHECK (principal > 0), 
    CONSTRAINT fk_loans_account_id_accounts FOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE SET NULL, 
    CONSTRAINT fk_loans_counterparty_id_counterparties FOREIGN KEY(counterparty_id) REFERENCES counterparties (id), 
    CONSTRAINT fk_loans_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE, 
    CONSTRAINT fk_loans_transaction_id_canonical_transactions FOREIGN KEY(transaction_id) REFERENCES canonical_transactions (id) ON DELETE SET NULL
);

CREATE INDEX ix_loans_counterparty_id ON loans (counterparty_id);

CREATE INDEX ix_loans_household_id ON loans (household_id);

CREATE TABLE recurring_expenses (
    household_id UUID NOT NULL, 
    name VARCHAR(160) NOT NULL, 
    amount NUMERIC(19, 4) NOT NULL, 
    currency VARCHAR(3) NOT NULL, 
    category_id UUID, 
    merchant_id UUID, 
    counterparty_id UUID, 
    frequency VARCHAR(10) NOT NULL, 
    next_due_date DATE NOT NULL, 
    is_subscription BOOLEAN NOT NULL, 
    status VARCHAR(10) NOT NULL, 
    detected BOOLEAN NOT NULL, 
    remind_days_before INTEGER NOT NULL, 
    last_transaction_id UUID, 
    notes TEXT NOT NULL, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_recurring_expenses PRIMARY KEY (id), 
    CONSTRAINT ck_recurring_expenses_frequency_valid CHECK (frequency in ('weekly','monthly','quarterly','yearly')), 
    CONSTRAINT ck_recurring_expenses_amount_positive CHECK (amount > 0), 
    CONSTRAINT fk_recurring_expenses_category_id_categories FOREIGN KEY(category_id) REFERENCES categories (id) ON DELETE SET NULL, 
    CONSTRAINT fk_recurring_expenses_counterparty_id_counterparties FOREIGN KEY(counterparty_id) REFERENCES counterparties (id) ON DELETE SET NULL, 
    CONSTRAINT fk_recurring_expenses_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE, 
    CONSTRAINT fk_recurring_expenses_last_transaction_id_canonical_tra_5e81 FOREIGN KEY(last_transaction_id) REFERENCES canonical_transactions (id) ON DELETE SET NULL, 
    CONSTRAINT fk_recurring_expenses_merchant_id_merchants FOREIGN KEY(merchant_id) REFERENCES merchants (id) ON DELETE SET NULL
);

CREATE INDEX ix_recurring_expenses_household_id ON recurring_expenses (household_id);

CREATE TABLE shared_expenses (
    household_id UUID NOT NULL, 
    transaction_id UUID NOT NULL, 
    description VARCHAR(300) NOT NULL, 
    total_amount NUMERIC(19, 4) NOT NULL, 
    currency VARCHAR(3) NOT NULL, 
    occurred_on DATE NOT NULL, 
    payer_counterparty_id UUID, 
    split_method VARCHAR(10) NOT NULL, 
    created_by UUID, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_shared_expenses PRIMARY KEY (id), 
    CONSTRAINT fk_shared_expenses_created_by_users FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL, 
    CONSTRAINT fk_shared_expenses_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE, 
    CONSTRAINT fk_shared_expenses_payer_counterparty_id_counterparties FOREIGN KEY(payer_counterparty_id) REFERENCES counterparties (id), 
    CONSTRAINT fk_shared_expenses_transaction_id_canonical_transactions FOREIGN KEY(transaction_id) REFERENCES canonical_transactions (id) ON DELETE CASCADE, 
    CONSTRAINT uq_shared_expenses_transaction_id UNIQUE (transaction_id)
);

CREATE INDEX ix_shared_expenses_household_id ON shared_expenses (household_id);

CREATE TABLE source_records (
    household_id UUID NOT NULL, 
    canonical_transaction_id UUID NOT NULL, 
    original_transaction_id UUID NOT NULL, 
    source_type VARCHAR(20) NOT NULL, 
    role VARCHAR(10) NOT NULL, 
    direction VARCHAR(10) NOT NULL, 
    amount NUMERIC(19, 4) NOT NULL, 
    currency VARCHAR(3) NOT NULL, 
    occurred_on DATE NOT NULL, 
    occurred_at TIMESTAMP WITH TIME ZONE, 
    merchant_raw VARCHAR(300) NOT NULL, 
    merchant_normalized VARCHAR(300) NOT NULL, 
    merchant_id UUID, 
    description VARCHAR(500) NOT NULL, 
    payment_method VARCHAR(20), 
    account_id UUID, 
    upi_txn_id VARCHAR(64), 
    utr VARCHAR(64), 
    bank_ref VARCHAR(64), 
    invoice_number VARCHAR(64), 
    order_id VARCHAR(64), 
    item_names JSONB NOT NULL, 
    document_id UUID, 
    statement_row_id UUID, 
    status VARCHAR(12) NOT NULL, 
    reconciliation_status VARCHAR(24) NOT NULL, 
    allocated_amount NUMERIC(19, 4) NOT NULL, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_source_records PRIMARY KEY (id), 
    CONSTRAINT ck_source_records_recon_valid CHECK (reconciliation_status in ('unmatched','suggested_match','matched','partially_paid','fully_paid','partially_reconciled','needs_review','disputed','reversed')), 
    CONSTRAINT ck_source_records_role_valid CHECK (role in ('bill','payment')), 
    CONSTRAINT ck_source_records_allocated_bounds CHECK (allocated_amount >= 0 and allocated_amount <= amount), 
    CONSTRAINT ck_source_records_amount_nonneg CHECK (amount >= 0), 
    CONSTRAINT fk_source_records_account_id_accounts FOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE SET NULL, 
    CONSTRAINT fk_source_records_canonical_transaction_id_canonical_tr_631a FOREIGN KEY(canonical_transaction_id) REFERENCES canonical_transactions (id) ON DELETE CASCADE, 
    CONSTRAINT fk_source_records_document_id_documents FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE SET NULL, 
    CONSTRAINT fk_source_records_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE, 
    CONSTRAINT fk_source_records_merchant_id_merchants FOREIGN KEY(merchant_id) REFERENCES merchants (id) ON DELETE SET NULL, 
    CONSTRAINT fk_source_records_original_transaction_id_canonical_tra_01c2 FOREIGN KEY(original_transaction_id) REFERENCES canonical_transactions (id) ON DELETE CASCADE, 
    CONSTRAINT fk_source_records_statement_row_id_statement_rows FOREIGN KEY(statement_row_id) REFERENCES statement_rows (id) ON DELETE SET NULL
);

CREATE INDEX ix_source_household_date ON source_records (household_id, occurred_on);

CREATE INDEX ix_source_records_bank_ref ON source_records (bank_ref);

CREATE INDEX ix_source_records_canonical_transaction_id ON source_records (canonical_transaction_id);

CREATE INDEX ix_source_records_invoice_number ON source_records (invoice_number);

CREATE INDEX ix_source_records_upi_txn_id ON source_records (upi_txn_id);

CREATE INDEX ix_source_records_utr ON source_records (utr);

CREATE UNIQUE INDEX uq_source_document ON source_records (document_id) WHERE document_id is not null;

CREATE UNIQUE INDEX uq_source_statement_row ON source_records (statement_row_id) WHERE statement_row_id is not null;

CREATE TABLE transaction_line_items (
    transaction_id UUID NOT NULL, 
    household_id UUID NOT NULL, 
    position INTEGER NOT NULL, 
    name VARCHAR(300) NOT NULL, 
    normalized_name VARCHAR(300) NOT NULL, 
    brand VARCHAR(120), 
    quantity NUMERIC(14, 4), 
    unit VARCHAR(20), 
    unit_price NUMERIC(19, 4), 
    discount NUMERIC(19, 4), 
    tax NUMERIC(19, 4), 
    line_total NUMERIC(19, 4), 
    category_id UUID, 
    unit_dimension VARCHAR(10), 
    base_quantity NUMERIC(14, 4), 
    id UUID NOT NULL, 
    CONSTRAINT pk_transaction_line_items PRIMARY KEY (id), 
    CONSTRAINT fk_transaction_line_items_category_id_categories FOREIGN KEY(category_id) REFERENCES categories (id) ON DELETE SET NULL, 
    CONSTRAINT fk_transaction_line_items_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE, 
    CONSTRAINT fk_transaction_line_items_transaction_id_canonical_transactions FOREIGN KEY(transaction_id) REFERENCES canonical_transactions (id) ON DELETE CASCADE
);

CREATE INDEX ix_line_items_household_name ON transaction_line_items (household_id, normalized_name);

CREATE INDEX ix_transaction_line_items_transaction_id ON transaction_line_items (transaction_id);

CREATE TABLE loan_repayments (
    loan_id UUID NOT NULL, 
    household_id UUID NOT NULL, 
    paid_on DATE NOT NULL, 
    principal_amount NUMERIC(19, 4) NOT NULL, 
    interest_amount NUMERIC(19, 4) NOT NULL, 
    transaction_id UUID, 
    interest_transaction_id UUID, 
    notes TEXT NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id UUID NOT NULL, 
    CONSTRAINT pk_loan_repayments PRIMARY KEY (id), 
    CONSTRAINT ck_loan_repayments_amount_positive CHECK (principal_amount + interest_amount > 0), 
    CONSTRAINT ck_loan_repayments_amounts_nonneg CHECK (principal_amount >= 0 and interest_amount >= 0), 
    CONSTRAINT fk_loan_repayments_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE, 
    CONSTRAINT fk_loan_repayments_interest_transaction_id_canonical_tr_f5a2 FOREIGN KEY(interest_transaction_id) REFERENCES canonical_transactions (id) ON DELETE SET NULL, 
    CONSTRAINT fk_loan_repayments_loan_id_loans FOREIGN KEY(loan_id) REFERENCES loans (id) ON DELETE CASCADE, 
    CONSTRAINT fk_loan_repayments_transaction_id_canonical_transactions FOREIGN KEY(transaction_id) REFERENCES canonical_transactions (id) ON DELETE SET NULL
);

CREATE INDEX ix_loan_repayments_loan_id ON loan_repayments (loan_id);

CREATE TABLE reconciliation_matches (
    household_id UUID NOT NULL, 
    kind VARCHAR(16) NOT NULL, 
    a_source_id UUID NOT NULL, 
    b_source_id UUID NOT NULL, 
    score INTEGER NOT NULL, 
    confidence VARCHAR(8) NOT NULL, 
    reasons JSONB NOT NULL, 
    conflict BOOLEAN NOT NULL, 
    amount_difference NUMERIC(19, 4) NOT NULL, 
    date_difference_days INTEGER NOT NULL, 
    merchant_similarity NUMERIC(4, 3) NOT NULL, 
    suggested_amount NUMERIC(19, 4), 
    status VARCHAR(12) NOT NULL, 
    origin VARCHAR(8) NOT NULL, 
    decided_by UUID, 
    decided_at TIMESTAMP WITH TIME ZONE, 
    note TEXT NOT NULL, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_reconciliation_matches PRIMARY KEY (id), 
    CONSTRAINT ck_reconciliation_matches_kind_valid CHECK (kind in ('bill_payment','duplicate','refund')), 
    CONSTRAINT ck_reconciliation_matches_status_valid CHECK (status in ('suggested','confirmed','rejected','unlinked')), 
    CONSTRAINT ck_reconciliation_matches_distinct_sources CHECK (a_source_id <> b_source_id), 
    CONSTRAINT fk_reconciliation_matches_a_source_id_source_records FOREIGN KEY(a_source_id) REFERENCES source_records (id) ON DELETE CASCADE, 
    CONSTRAINT fk_reconciliation_matches_b_source_id_source_records FOREIGN KEY(b_source_id) REFERENCES source_records (id) ON DELETE CASCADE, 
    CONSTRAINT fk_reconciliation_matches_decided_by_users FOREIGN KEY(decided_by) REFERENCES users (id) ON DELETE SET NULL, 
    CONSTRAINT fk_reconciliation_matches_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE
);

CREATE INDEX ix_reconciliation_matches_a_source_id ON reconciliation_matches (a_source_id);

CREATE INDEX ix_reconciliation_matches_b_source_id ON reconciliation_matches (b_source_id);

CREATE INDEX ix_reconciliation_matches_household_id ON reconciliation_matches (household_id);

CREATE UNIQUE INDEX uq_recon_match_pair ON reconciliation_matches (household_id, least(a_source_id, b_source_id), greatest(a_source_id, b_source_id), kind);

CREATE TABLE shared_expense_participants (
    shared_expense_id UUID NOT NULL, 
    household_id UUID NOT NULL, 
    counterparty_id UUID, 
    share_amount NUMERIC(19, 4) NOT NULL, 
    settled_amount NUMERIC(19, 4) NOT NULL, 
    due_date DATE, 
    id UUID NOT NULL, 
    CONSTRAINT pk_shared_expense_participants PRIMARY KEY (id), 
    CONSTRAINT ck_shared_expense_participants_settled_bounds CHECK (settled_amount >= 0 and settled_amount <= share_amount), 
    CONSTRAINT ck_shared_expense_participants_share_nonneg CHECK (share_amount >= 0), 
    CONSTRAINT fk_shared_expense_participants_counterparty_id_counterparties FOREIGN KEY(counterparty_id) REFERENCES counterparties (id), 
    CONSTRAINT fk_shared_expense_participants_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE, 
    CONSTRAINT fk_shared_expense_participants_shared_expense_id_shared_94ce FOREIGN KEY(shared_expense_id) REFERENCES shared_expenses (id) ON DELETE CASCADE, 
    CONSTRAINT uq_shared_expense_participants_shared_expense_id_counte_b918 UNIQUE NULLS NOT DISTINCT (shared_expense_id, counterparty_id)
);

CREATE INDEX ix_shared_expense_participants_shared_expense_id ON shared_expense_participants (shared_expense_id);

CREATE TABLE reconciliation_allocations (
    household_id UUID NOT NULL, 
    match_id UUID, 
    payment_source_id UUID NOT NULL, 
    bill_source_id UUID NOT NULL, 
    amount NUMERIC(19, 4) NOT NULL, 
    status VARCHAR(10) NOT NULL, 
    created_by UUID, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    removed_by UUID, 
    removed_at TIMESTAMP WITH TIME ZONE, 
    id UUID NOT NULL, 
    CONSTRAINT pk_reconciliation_allocations PRIMARY KEY (id), 
    CONSTRAINT ck_reconciliation_allocations_amount_positive CHECK (amount > 0), 
    CONSTRAINT ck_reconciliation_allocations_distinct_sources CHECK (payment_source_id <> bill_source_id), 
    CONSTRAINT fk_reconciliation_allocations_bill_source_id_source_records FOREIGN KEY(bill_source_id) REFERENCES source_records (id) ON DELETE CASCADE, 
    CONSTRAINT fk_reconciliation_allocations_created_by_users FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL, 
    CONSTRAINT fk_reconciliation_allocations_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE, 
    CONSTRAINT fk_reconciliation_allocations_match_id_reconciliation_matches FOREIGN KEY(match_id) REFERENCES reconciliation_matches (id) ON DELETE SET NULL, 
    CONSTRAINT fk_reconciliation_allocations_payment_source_id_source_records FOREIGN KEY(payment_source_id) REFERENCES source_records (id) ON DELETE CASCADE, 
    CONSTRAINT fk_reconciliation_allocations_removed_by_users FOREIGN KEY(removed_by) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_reconciliation_allocations_bill_source_id ON reconciliation_allocations (bill_source_id);

CREATE INDEX ix_reconciliation_allocations_household_id ON reconciliation_allocations (household_id);

CREATE INDEX ix_reconciliation_allocations_payment_source_id ON reconciliation_allocations (payment_source_id);

CREATE UNIQUE INDEX uq_active_allocation ON reconciliation_allocations (payment_source_id, bill_source_id) WHERE status = 'active';

CREATE TABLE shared_expense_settlements (
    participant_id UUID NOT NULL, 
    household_id UUID NOT NULL, 
    transaction_id UUID NOT NULL, 
    amount NUMERIC(19, 4) NOT NULL, 
    settled_on DATE NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id UUID NOT NULL, 
    CONSTRAINT pk_shared_expense_settlements PRIMARY KEY (id), 
    CONSTRAINT ck_shared_expense_settlements_amount_positive CHECK (amount > 0), 
    CONSTRAINT fk_shared_expense_settlements_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE, 
    CONSTRAINT fk_shared_expense_settlements_participant_id_shared_exp_4f1c FOREIGN KEY(participant_id) REFERENCES shared_expense_participants (id) ON DELETE CASCADE, 
    CONSTRAINT fk_shared_expense_settlements_transaction_id_canonical__959c FOREIGN KEY(transaction_id) REFERENCES canonical_transactions (id) ON DELETE CASCADE
);

CREATE INDEX ix_shared_expense_settlements_participant_id ON shared_expense_settlements (participant_id);

CREATE TABLE reconciliation_audit_logs (
    household_id UUID NOT NULL, 
    match_id UUID, 
    allocation_id UUID, 
    action VARCHAR(32) NOT NULL, 
    actor_id UUID, 
    before JSONB, 
    after JSONB, 
    note TEXT NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id UUID NOT NULL, 
    CONSTRAINT pk_reconciliation_audit_logs PRIMARY KEY (id), 
    CONSTRAINT fk_reconciliation_audit_logs_actor_id_users FOREIGN KEY(actor_id) REFERENCES users (id) ON DELETE SET NULL, 
    CONSTRAINT fk_reconciliation_audit_logs_allocation_id_reconciliati_4761 FOREIGN KEY(allocation_id) REFERENCES reconciliation_allocations (id) ON DELETE SET NULL, 
    CONSTRAINT fk_reconciliation_audit_logs_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE, 
    CONSTRAINT fk_reconciliation_audit_logs_match_id_reconciliation_matches FOREIGN KEY(match_id) REFERENCES reconciliation_matches (id) ON DELETE SET NULL
);

CREATE INDEX ix_reconciliation_audit_logs_household_id ON reconciliation_audit_logs (household_id);

CREATE INDEX ix_reconciliation_audit_logs_match_id ON reconciliation_audit_logs (match_id);

INSERT INTO alembic_version (version_num) VALUES ('5fe15cd05018') RETURNING alembic_version.version_num;

-- Running upgrade 5fe15cd05018 -> 37967cd4bb6d

CREATE TABLE credit_card_statements (
    household_id UUID NOT NULL, 
    account_id UUID NOT NULL, 
    period_start DATE NOT NULL, 
    statement_date DATE NOT NULL, 
    due_date DATE NOT NULL, 
    total_due NUMERIC(19, 4) NOT NULL, 
    minimum_due NUMERIC(19, 4) NOT NULL, 
    currency VARCHAR(3) NOT NULL, 
    interest_charged NUMERIC(19, 4) NOT NULL, 
    fees_charged NUMERIC(19, 4) NOT NULL, 
    charge_transaction_ids JSONB NOT NULL, 
    document_id UUID, 
    notes TEXT NOT NULL, 
    created_by UUID, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_credit_card_statements PRIMARY KEY (id), 
    CONSTRAINT ck_credit_card_statements_charges_nonneg CHECK (interest_charged >= 0 and fees_charged >= 0), 
    CONSTRAINT ck_credit_card_statements_dates_ordered CHECK (period_start <= statement_date and statement_date <= due_date), 
    CONSTRAINT ck_credit_card_statements_amounts_valid CHECK (total_due >= 0 and minimum_due >= 0 and minimum_due <= total_due), 
    CONSTRAINT fk_credit_card_statements_account_id_accounts FOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE CASCADE, 
    CONSTRAINT fk_credit_card_statements_created_by_users FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL, 
    CONSTRAINT fk_credit_card_statements_document_id_documents FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE SET NULL, 
    CONSTRAINT fk_credit_card_statements_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE, 
    CONSTRAINT uq_credit_card_statements_account_id_statement_date UNIQUE (account_id, statement_date)
);

CREATE INDEX ix_credit_card_statements_account_id ON credit_card_statements (account_id);

CREATE INDEX ix_credit_card_statements_household_id ON credit_card_statements (household_id);

CREATE TABLE credit_card_bill_payments (
    household_id UUID NOT NULL, 
    statement_id UUID NOT NULL, 
    transaction_id UUID NOT NULL, 
    amount NUMERIC(19, 4) NOT NULL, 
    created_by UUID, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id UUID NOT NULL, 
    CONSTRAINT pk_credit_card_bill_payments PRIMARY KEY (id), 
    CONSTRAINT ck_credit_card_bill_payments_amount_positive CHECK (amount > 0), 
    CONSTRAINT fk_credit_card_bill_payments_created_by_users FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL, 
    CONSTRAINT fk_credit_card_bill_payments_household_id_households FOREIGN KEY(household_id) REFERENCES households (id) ON DELETE CASCADE, 
    CONSTRAINT fk_credit_card_bill_payments_statement_id_credit_card_s_dc42 FOREIGN KEY(statement_id) REFERENCES credit_card_statements (id) ON DELETE CASCADE, 
    CONSTRAINT fk_credit_card_bill_payments_transaction_id_canonical_t_9ad7 FOREIGN KEY(transaction_id) REFERENCES canonical_transactions (id) ON DELETE CASCADE, 
    CONSTRAINT uq_credit_card_bill_payments_statement_id_transaction_id UNIQUE (statement_id, transaction_id)
);

CREATE INDEX ix_credit_card_bill_payments_statement_id ON credit_card_bill_payments (statement_id);

CREATE INDEX ix_credit_card_bill_payments_transaction_id ON credit_card_bill_payments (transaction_id);

ALTER TABLE accounts ADD COLUMN credit_limit NUMERIC(19, 4);

ALTER TABLE accounts ADD COLUMN statement_day INTEGER;

ALTER TABLE accounts ADD COLUMN due_day INTEGER;

ALTER TABLE accounts ADD CONSTRAINT ck_accounts_credit_limit_nonneg CHECK (credit_limit is null or credit_limit >= 0);

ALTER TABLE accounts ADD CONSTRAINT ck_accounts_statement_day_valid CHECK (statement_day is null or statement_day between 1 and 31);

ALTER TABLE accounts ADD CONSTRAINT ck_accounts_due_day_valid CHECK (due_day is null or due_day between 1 and 31);

UPDATE alembic_version SET version_num='37967cd4bb6d' WHERE alembic_version.version_num = '5fe15cd05018';

-- Running upgrade 37967cd4bb6d -> d24adaa3ea18

ALTER TABLE canonical_transactions ADD COLUMN category_reasons JSONB DEFAULT '[]'::jsonb NOT NULL;

ALTER TABLE extracted_documents ADD COLUMN category_reasons JSONB DEFAULT '[]'::jsonb NOT NULL;

UPDATE alembic_version SET version_num='d24adaa3ea18' WHERE alembic_version.version_num = '37967cd4bb6d';

-- Running upgrade d24adaa3ea18 -> 0f9e648403eb

ALTER TABLE email_tokens ADD COLUMN attempts INTEGER DEFAULT '0' NOT NULL;

UPDATE alembic_version SET version_num='0f9e648403eb' WHERE alembic_version.version_num = 'd24adaa3ea18';

-- Running upgrade 0f9e648403eb -> 6c1e2b7a9d40

UPDATE households SET name = left(name, length(name) - length('Household')) || 'Workspace' WHERE name LIKE '%%''s Household' OR name = 'My Household';

UPDATE households SET name = 'Demo Workspace (sample data)' WHERE name = 'Demo Household (sample data)';

UPDATE alembic_version SET version_num='6c1e2b7a9d40' WHERE alembic_version.version_num = '0f9e648403eb';

COMMIT;
