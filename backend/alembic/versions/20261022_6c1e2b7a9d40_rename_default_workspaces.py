"""rename auto-generated "<name>'s Household" workspaces to "<name>'s Workspace"

The product now says "workspace" instead of "household". Only names that match the old automatic default
(including the demo seed's) are changed; names people typed themselves are left alone.

Revision ID: 6c1e2b7a9d40
Revises: 0f9e648403eb
Create Date: 2026-10-22 14:05:00
"""
from alembic import op


revision = '6c1e2b7a9d40'
down_revision = '0f9e648403eb'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE households SET name = left(name, length(name) - length('Household')) || 'Workspace' WHERE name LIKE '%''s Household' OR name = 'My Household'")
    op.execute("UPDATE households SET name = 'Demo Workspace (sample data)' WHERE name = 'Demo Household (sample data)'")


def downgrade() -> None:
    op.execute("UPDATE households SET name = left(name, length(name) - length('Workspace')) || 'Household' WHERE name LIKE '%''s Workspace' OR name = 'My Workspace'")
    op.execute("UPDATE households SET name = 'Demo Household (sample data)' WHERE name = 'Demo Workspace (sample data)'")
