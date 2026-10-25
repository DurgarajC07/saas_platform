"""initial_schema

Creates the base schema (users, organizations, rbac, billing, features,
audit, security, api management, notifications, files, system settings)
that every later migration builds on. Mirrors app/modules/*/models.py
exactly (see alembic/env.py for the import/dependency order used here).

Revision ID: f3a1c9d04b7e
Revises:
Create Date: 2026-03-01 09:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f3a1c9d04b7e'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users ────────────────────────────────────────────────────────────
    op.create_table(
        'users',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.Text(), nullable=True),
        sa.Column('first_name', sa.String(length=150), nullable=True),
        sa.Column('last_name', sa.String(length=150), nullable=True),
        sa.Column('display_name', sa.String(length=255), nullable=True),
        sa.Column('phone', sa.String(length=50), nullable=True),
        sa.Column('avatar_url', sa.Text(), nullable=True),
        sa.Column('is_platform_admin', sa.Boolean(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('email_verified', sa.Boolean(), nullable=False),
        sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('two_factor_enabled', sa.Boolean(), nullable=False),
        sa.Column('two_factor_method', sa.String(length=50), nullable=True),
        sa.Column('two_factor_secret', sa.Text(), nullable=True),
        sa.Column('password_changed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('failed_login_attempts', sa.Integer(), nullable=False),
        sa.Column('account_locked_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_login_ip', postgresql.INET(), nullable=True),
        sa.Column('last_active_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('timezone', sa.String(length=100), nullable=False),
        sa.Column('locale', sa.String(length=20), nullable=False),
        sa.Column('preferences', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
    )
    op.create_index('ix_users_email', 'users', ['email'], unique=True)
    op.create_index('ix_users_is_active', 'users', ['is_active'], unique=False)
    op.create_index('ix_users_email_active', 'users', ['email', 'is_active'], unique=False)
    op.create_index('ix_users_deleted_at', 'users', ['deleted_at'], unique=False)

    # ── organizations ────────────────────────────────────────────────────
    op.create_table(
        'organizations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('slug', sa.String(length=255), nullable=False),
        sa.Column('logo_url', sa.Text(), nullable=True),
        sa.Column('website', sa.String(length=255), nullable=True),
        sa.Column('industry', sa.String(length=150), nullable=True),
        sa.Column('owner_user_id', sa.UUID(), nullable=True),
        sa.Column('timezone', sa.String(length=100), nullable=False),
        sa.Column('locale', sa.String(length=20), nullable=False),
        sa.Column('currency', sa.String(length=10), nullable=False),
        sa.Column('settings', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('max_seats', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('onboarding_completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug'),
    )
    op.create_index('ix_organizations_slug', 'organizations', ['slug'], unique=True)
    op.create_index('ix_organizations_owner_user_id', 'organizations', ['owner_user_id'], unique=False)
    op.create_index('ix_organizations_is_active', 'organizations', ['is_active'], unique=False)
    op.create_index('ix_organizations_deleted_at', 'organizations', ['deleted_at'], unique=False)

    # ── sessions ─────────────────────────────────────────────────────────
    op.create_table(
        'sessions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=True),
        sa.Column('token_hash', sa.Text(), nullable=False),
        sa.Column('ip_address', postgresql.INET(), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('device_type', sa.String(length=50), nullable=True),
        sa.Column('last_active_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash'),
    )
    op.create_index('ix_sessions_user_id', 'sessions', ['user_id'], unique=False)
    op.create_index('ix_sessions_expires_at', 'sessions', ['expires_at'], unique=False)

    # ── verification_tokens ──────────────────────────────────────────────
    op.create_table(
        'verification_tokens',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('type', sa.String(length=50), nullable=False),
        sa.Column('token_hash', sa.Text(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash'),
    )
    op.create_index('ix_verification_tokens_user_type', 'verification_tokens', ['user_id', 'type'], unique=False)

    # ── two_factor_backup_codes ──────────────────────────────────────────
    op.create_table(
        'two_factor_backup_codes',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('code_hash', sa.Text(), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_two_factor_backup_codes_user_id', 'two_factor_backup_codes', ['user_id'], unique=False)

    # ── user_oauth_accounts ──────────────────────────────────────────────
    op.create_table(
        'user_oauth_accounts',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('provider', sa.String(length=50), nullable=False),
        sa.Column('provider_user_id', sa.String(length=255), nullable=False),
        sa.Column('provider_email', sa.String(length=255), nullable=True),
        sa.Column('access_token', sa.Text(), nullable=True),
        sa.Column('refresh_token', sa.Text(), nullable=True),
        sa.Column('token_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('raw_profile', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider', 'provider_user_id', name='uq_oauth_provider_user'),
        sa.UniqueConstraint('user_id', 'provider', name='uq_oauth_user_provider'),
    )

    # ── organization_domains ─────────────────────────────────────────────
    op.create_table(
        'organization_domains',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('domain', sa.String(length=255), nullable=False),
        sa.Column('is_verified', sa.Boolean(), nullable=False),
        sa.Column('verification_token', sa.String(length=255), nullable=True),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'domain', name='uq_org_domain'),
    )
    op.create_index('ix_organization_domains_organization_id', 'organization_domains', ['organization_id'], unique=False)

    # ── organization_users ───────────────────────────────────────────────
    op.create_table(
        'organization_users',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('org_role', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('joined_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('invited_by', sa.UUID(), nullable=True),
        sa.Column('suspended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('suspension_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'user_id', name='uq_org_user'),
    )
    op.create_index('ix_organization_users_organization_id', 'organization_users', ['organization_id'], unique=False)
    op.create_index('ix_organization_users_user_id', 'organization_users', ['user_id'], unique=False)
    op.create_index('ix_organization_users_status', 'organization_users', ['status'], unique=False)

    # ── invitations ──────────────────────────────────────────────────────
    op.create_table(
        'invitations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('token', sa.String(length=255), nullable=False),
        sa.Column('role_id', sa.UUID(), nullable=True),
        sa.Column('org_role', sa.String(length=50), nullable=False),
        sa.Column('invited_by', sa.UUID(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'email', name='uq_invitation_org_email'),
        sa.UniqueConstraint('token'),
    )
    op.create_index('ix_invitations_organization_id', 'invitations', ['organization_id'], unique=False)
    op.create_index('ix_invitations_token', 'invitations', ['token'], unique=True)
    op.create_index('ix_invitations_status', 'invitations', ['status'], unique=False)

    # ── roles ────────────────────────────────────────────────────────────
    op.create_table(
        'roles',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('display_name', sa.String(length=150), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('organization_id', sa.UUID(), nullable=True),
        sa.Column('is_system_role', sa.Boolean(), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', 'organization_id', name='uq_role_name_org'),
    )
    op.create_index('ix_roles_organization_id', 'roles', ['organization_id'], unique=False)
    op.create_index('ix_roles_is_system_role', 'roles', ['is_system_role'], unique=False)

    # ── permissions ──────────────────────────────────────────────────────
    op.create_table(
        'permissions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('display_name', sa.String(length=200), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('module', sa.String(length=100), nullable=False),
        sa.Column('resource', sa.String(length=100), nullable=False),
        sa.Column('action', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
        sa.UniqueConstraint('module', 'resource', 'action', name='uq_permission_module_resource_action'),
    )
    op.create_index('ix_permissions_name', 'permissions', ['name'], unique=True)
    op.create_index('ix_permissions_module', 'permissions', ['module'], unique=False)

    # ── role_permissions ─────────────────────────────────────────────────
    op.create_table(
        'role_permissions',
        sa.Column('role_id', sa.UUID(), nullable=False),
        sa.Column('permission_id', sa.UUID(), nullable=False),
        sa.Column('conditions', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('granted_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['permission_id'], ['permissions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('role_id', 'permission_id'),
    )

    # ── organization_user_roles ──────────────────────────────────────────
    op.create_table(
        'organization_user_roles',
        sa.Column('organization_user_id', sa.UUID(), nullable=False),
        sa.Column('role_id', sa.UUID(), nullable=False),
        sa.Column('assigned_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('assigned_by', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['organization_user_id'], ['organization_users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('organization_user_id', 'role_id'),
    )

    # ── subscription_plans ───────────────────────────────────────────────
    op.create_table(
        'subscription_plans',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('slug', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('price_monthly', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('price_yearly', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('currency', sa.String(length=10), nullable=False),
        sa.Column('max_seats', sa.Integer(), nullable=True),
        sa.Column('max_storage_mb', sa.BigInteger(), nullable=True),
        sa.Column('trial_days', sa.Integer(), nullable=False),
        sa.Column('features', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('display_order', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug'),
    )
    op.create_index('ix_subscription_plans_slug', 'subscription_plans', ['slug'], unique=True)
    op.create_index('ix_subscription_plans_is_active', 'subscription_plans', ['is_active'], unique=False)

    # ── subscriptions ────────────────────────────────────────────────────
    op.create_table(
        'subscriptions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('plan_id', sa.UUID(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('billing_cycle', sa.String(length=20), nullable=False),
        sa.Column('current_period_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('trial_ends_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('canceled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancellation_reason', sa.Text(), nullable=True),
        sa.Column('external_provider', sa.String(length=50), nullable=True),
        sa.Column('external_subscription_id', sa.String(length=255), nullable=True),
        sa.Column('external_customer_id', sa.String(length=255), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['plan_id'], ['subscription_plans.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_subscriptions_organization_id', 'subscriptions', ['organization_id'], unique=False)
    op.create_index('ix_subscriptions_org_status', 'subscriptions', ['organization_id', 'status'], unique=False)

    # ── invoices ─────────────────────────────────────────────────────────
    op.create_table(
        'invoices',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('subscription_id', sa.UUID(), nullable=True),
        sa.Column('invoice_number', sa.String(length=100), nullable=False),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('currency', sa.String(length=10), nullable=False),
        sa.Column('tax_amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('total_amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('due_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('external_invoice_id', sa.String(length=255), nullable=True),
        sa.Column('invoice_pdf_url', sa.Text(), nullable=True),
        sa.Column('billing_details', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['subscription_id'], ['subscriptions.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('invoice_number'),
    )
    op.create_index('ix_invoices_organization_id', 'invoices', ['organization_id'], unique=False)
    op.create_index('ix_invoices_status', 'invoices', ['status'], unique=False)

    # ── payment_methods ──────────────────────────────────────────────────
    op.create_table(
        'payment_methods',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('type', sa.String(length=50), nullable=False),
        sa.Column('provider', sa.String(length=50), nullable=True),
        sa.Column('external_payment_method_id', sa.String(length=255), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=False),
        sa.Column('last_four', sa.String(length=4), nullable=True),
        sa.Column('card_brand', sa.String(length=50), nullable=True),
        sa.Column('expires_month', sa.Integer(), nullable=True),
        sa.Column('expires_year', sa.Integer(), nullable=True),
        sa.Column('billing_address', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_payment_methods_organization_id', 'payment_methods', ['organization_id'], unique=False)
    op.create_index('ix_payment_methods_is_default', 'payment_methods', ['is_default'], unique=False)
    op.create_index('ix_payment_methods_deleted_at', 'payment_methods', ['deleted_at'], unique=False)

    # ── features ─────────────────────────────────────────────────────────
    op.create_table(
        'features',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('key', sa.String(length=150), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('module', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key'),
    )
    op.create_index('ix_features_key', 'features', ['key'], unique=True)
    op.create_index('ix_features_module', 'features', ['module'], unique=False)

    # ── plan_features ────────────────────────────────────────────────────
    op.create_table(
        'plan_features',
        sa.Column('plan_id', sa.UUID(), nullable=False),
        sa.Column('feature_id', sa.UUID(), nullable=False),
        sa.Column('limit_value', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['plan_id'], ['subscription_plans.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['feature_id'], ['features.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('plan_id', 'feature_id'),
    )

    # ── organization_feature_overrides ───────────────────────────────────
    op.create_table(
        'organization_feature_overrides',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('feature_id', sa.UUID(), nullable=False),
        sa.Column('limit_value', sa.Integer(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['feature_id'], ['features.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'feature_id', name='uq_org_feature_override'),
    )
    op.create_index('ix_organization_feature_overrides_organization_id', 'organization_feature_overrides', ['organization_id'], unique=False)

    # ── audit_logs ───────────────────────────────────────────────────────
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=True),
        sa.Column('actor_user_id', sa.UUID(), nullable=True),
        sa.Column('actor_type', sa.String(length=50), nullable=False),
        sa.Column('action', sa.String(length=100), nullable=False),
        sa.Column('resource_type', sa.String(length=100), nullable=True),
        sa.Column('resource_id', sa.UUID(), nullable=True),
        sa.Column('old_values', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('new_values', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('ip_address', postgresql.INET(), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('request_id', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_audit_logs_organization_id', 'audit_logs', ['organization_id'], unique=False)
    op.create_index('ix_audit_logs_org', 'audit_logs', ['organization_id'], unique=False)
    op.create_index('ix_audit_logs_actor_user_id', 'audit_logs', ['actor_user_id'], unique=False)
    op.create_index('ix_audit_logs_actor', 'audit_logs', ['actor_user_id'], unique=False)
    op.create_index('ix_audit_logs_created_at', 'audit_logs', ['created_at'], unique=False)
    op.create_index('ix_audit_logs_resource', 'audit_logs', ['resource_type', 'resource_id'], unique=False)

    # ── login_attempts ───────────────────────────────────────────────────
    op.create_table(
        'login_attempts',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('ip_address', postgresql.INET(), nullable=False),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('method', sa.String(length=50), nullable=False),
        sa.Column('is_success', sa.Boolean(), nullable=True),
        sa.Column('failure_reason', sa.String(length=100), nullable=True),
        sa.Column('attempted_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_login_attempts_email', 'login_attempts', ['email'], unique=False)
    op.create_index('ix_login_attempts_ip_address', 'login_attempts', ['ip_address'], unique=False)
    op.create_index('ix_login_attempts_ip', 'login_attempts', ['ip_address'], unique=False)
    op.create_index('ix_login_attempts_attempted_at', 'login_attempts', ['attempted_at'], unique=False)
    op.create_index('ix_login_attempts_at', 'login_attempts', ['attempted_at'], unique=False)

    # ── blocked_ips ──────────────────────────────────────────────────────
    op.create_table(
        'blocked_ips',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('ip_address', postgresql.INET(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('blocked_by', sa.UUID(), nullable=True),
        sa.Column('blocked_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('ip_address'),
    )
    op.create_index('ix_blocked_ips_ip_address', 'blocked_ips', ['ip_address'], unique=True)
    op.create_index('ix_blocked_ips_is_active', 'blocked_ips', ['is_active'], unique=False)

    # ── api_keys ─────────────────────────────────────────────────────────
    op.create_table(
        'api_keys',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('created_by', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('key_prefix', sa.String(length=10), nullable=False),
        sa.Column('key_hash', sa.Text(), nullable=False),
        sa.Column('scopes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('rate_limit_per_minute', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_used_ip', postgresql.INET(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key_hash'),
    )
    op.create_index('ix_api_keys_organization_id', 'api_keys', ['organization_id'], unique=False)
    op.create_index('ix_api_keys_key_prefix', 'api_keys', ['key_prefix'], unique=False)

    # ── webhooks ─────────────────────────────────────────────────────────
    op.create_table(
        'webhooks',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('created_by', sa.UUID(), nullable=False),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('secret', sa.Text(), nullable=False),
        sa.Column('events', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('last_triggered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('failure_count', sa.Integer(), nullable=False),
        sa.Column('last_failure_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_webhooks_organization_id', 'webhooks', ['organization_id'], unique=False)
    op.create_index('ix_webhooks_is_active', 'webhooks', ['is_active'], unique=False)
    op.create_index('ix_webhooks_deleted_at', 'webhooks', ['deleted_at'], unique=False)

    # ── webhook_deliveries ───────────────────────────────────────────────
    op.create_table(
        'webhook_deliveries',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('webhook_id', sa.UUID(), nullable=False),
        sa.Column('event', sa.String(length=100), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('response_status', sa.Integer(), nullable=True),
        sa.Column('response_body', sa.Text(), nullable=True),
        sa.Column('response_time_ms', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['webhook_id'], ['webhooks.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_webhook_deliveries_webhook_id', 'webhook_deliveries', ['webhook_id'], unique=False)
    op.create_index('ix_webhook_deliveries_status', 'webhook_deliveries', ['status'], unique=False)
    op.create_index('ix_webhook_deliveries_created_at', 'webhook_deliveries', ['created_at'], unique=False)
    op.create_index('ix_webhook_deliveries_webhook_created', 'webhook_deliveries', ['webhook_id', 'created_at'], unique=False)

    # ── notifications ────────────────────────────────────────────────────
    op.create_table(
        'notifications',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=True),
        sa.Column('type', sa.String(length=100), nullable=False),
        sa.Column('channel', sa.String(length=50), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=True),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('is_read', sa.Boolean(), nullable=False),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_notifications_user_id', 'notifications', ['user_id'], unique=False)
    op.create_index('ix_notifications_user_read', 'notifications', ['user_id', 'is_read'], unique=False)
    op.create_index('ix_notifications_created_at', 'notifications', ['created_at'], unique=False)

    # ── notification_preferences ─────────────────────────────────────────
    op.create_table(
        'notification_preferences',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('notification_type', sa.String(length=100), nullable=False),
        sa.Column('channel', sa.String(length=50), nullable=False),
        sa.Column('is_enabled', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'notification_type', 'channel', name='uq_notification_pref_user_type_channel'),
    )
    op.create_index('ix_notification_preferences_user_id', 'notification_preferences', ['user_id'], unique=False)

    # ── files ────────────────────────────────────────────────────────────
    op.create_table(
        'files',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=True),
        sa.Column('uploaded_by', sa.UUID(), nullable=False),
        sa.Column('file_name', sa.String(length=500), nullable=False),
        sa.Column('original_name', sa.String(length=500), nullable=False),
        sa.Column('mime_type', sa.String(length=150), nullable=False),
        sa.Column('file_size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('storage_provider', sa.String(length=50), nullable=False),
        sa.Column('storage_path', sa.Text(), nullable=False),
        sa.Column('attachable_type', sa.String(length=100), nullable=True),
        sa.Column('attachable_id', sa.UUID(), nullable=True),
        sa.Column('checksum', sa.String(length=255), nullable=True),
        sa.Column('is_public', sa.Boolean(), nullable=False),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_files_organization_id', 'files', ['organization_id'], unique=False)
    op.create_index('ix_files_org', 'files', ['organization_id'], unique=False)
    op.create_index('ix_files_attachable', 'files', ['attachable_type', 'attachable_id'], unique=False)
    op.create_index('ix_files_deleted_at', 'files', ['deleted_at'], unique=False)

    # ── system_settings ──────────────────────────────────────────────────
    op.create_table(
        'system_settings',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('key', sa.String(length=255), nullable=False),
        sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_public', sa.Boolean(), nullable=False),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key'),
    )
    op.create_index('ix_system_settings_key', 'system_settings', ['key'], unique=True)
    op.create_index('ix_system_settings_is_public', 'system_settings', ['is_public'], unique=False)


def downgrade() -> None:
    op.drop_table('system_settings')
    op.drop_table('files')
    op.drop_table('notification_preferences')
    op.drop_table('notifications')
    op.drop_table('webhook_deliveries')
    op.drop_table('webhooks')
    op.drop_table('api_keys')
    op.drop_table('blocked_ips')
    op.drop_table('login_attempts')
    op.drop_table('audit_logs')
    op.drop_table('organization_feature_overrides')
    op.drop_table('plan_features')
    op.drop_table('features')
    op.drop_table('payment_methods')
    op.drop_table('invoices')
    op.drop_table('subscriptions')
    op.drop_table('subscription_plans')
    op.drop_table('organization_user_roles')
    op.drop_table('role_permissions')
    op.drop_table('permissions')
    op.drop_table('roles')
    op.drop_table('invitations')
    op.drop_table('organization_users')
    op.drop_table('organization_domains')
    op.drop_table('user_oauth_accounts')
    op.drop_table('two_factor_backup_codes')
    op.drop_table('verification_tokens')
    op.drop_table('sessions')
    op.drop_table('organizations')
    op.drop_table('users')
