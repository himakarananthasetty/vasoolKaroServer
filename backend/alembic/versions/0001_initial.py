r"""VasoolKaro initial schema

Revision ID: 0001_initial
Revises: 
Create Date: 2026-11-18

"""
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
        op.execute("""\
-- citext replaced by lower(email) unique index
""")
        op.execute("""\
DO $$ BEGIN CREATE TYPE user_account_type AS ENUM ('shopper', 'retailer'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
""")
        op.execute("""\
DO $$ BEGIN CREATE TYPE admin_role AS ENUM ('admin', 'super_admin'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
""")
        op.execute("""\
DO $$ BEGIN CREATE TYPE receipt_status AS ENUM ('SUBMITTED', 'REVIEWING', 'APPROVED', 'PAID', 'REJECTED', 'REVERSED'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
""")
        op.execute("""\
DO $$ BEGIN CREATE TYPE ledger_entry_type AS ENUM ('RECEIPT_CASHBACK', 'REFERRAL_BONUS', 'REVERSAL'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
""")
        op.execute("""\
DO $$ BEGIN CREATE TYPE payout_method AS ENUM ('UPI', 'CASH'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
""")
        op.execute("""\
DO $$ BEGIN CREATE TYPE payout_status AS ENUM ('REQUESTED', 'PAID', 'CANCELLED'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
""")
        op.execute("""\
DO $$ BEGIN CREATE TYPE referral_reason AS ENUM ('INVITE_ACCEPTED', 'INVITE_SENT'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
""")
        op.execute("""\
DO $$ BEGIN CREATE TYPE notification_kind AS ENUM ('RECEIPT_APPROVED', 'RECEIPT_REJECTED'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
""")
        op.execute("""\
DO $$ BEGIN CREATE TYPE support_topic AS ENUM ('ACCOUNT', 'CASHBACK', 'OFFERS', 'OTHER'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
""")
        op.execute("""\
DO $$ BEGIN CREATE TYPE support_status AS ENUM ('OPEN', 'ANSWERED', 'CLOSED'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
""")
        op.execute("""\
CREATE TABLE rate_limit_events (
	id SERIAL NOT NULL, 
	subject_kind VARCHAR(20) NOT NULL, 
	subject_id VARCHAR(64) NOT NULL, 
	action VARCHAR(40) NOT NULL, 
	occurred_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);
""")
        op.execute("""\
CREATE INDEX idx_rle_window ON rate_limit_events (action, subject_kind, subject_id, occurred_at);
""")
        op.execute("""\
CREATE TABLE users (
	id UUID NOT NULL, 
	email TEXT NOT NULL, 
	password_hash TEXT NOT NULL, 
	full_name VARCHAR(120), 
	account_type user_account_type DEFAULT 'shopper' NOT NULL, 
	business_name VARCHAR(80), 
	phone_number VARCHAR(20), 
	date_of_birth DATE, 
	address VARCHAR(200), 
	avatar_path TEXT, 
	referral_code VARCHAR(8) NOT NULL, 
	referred_by UUID, 
	notify_offers BOOLEAN DEFAULT true NOT NULL, 
	notify_receipts BOOLEAN DEFAULT true NOT NULL, 
	marketing_opt_in BOOLEAN DEFAULT false NOT NULL, 
	personalised_offers BOOLEAN DEFAULT true NOT NULL, 
	deactivated_at TIMESTAMP WITH TIME ZONE, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT chk_users_retailer_business_name CHECK ((account_type = 'shopper') OR (business_name IS NOT NULL AND char_length(business_name) BETWEEN 2 AND 80)), 
	CONSTRAINT chk_users_dob_age CHECK (date_of_birth IS NULL OR date_of_birth <= CURRENT_DATE - INTERVAL '13 years'), 
	CONSTRAINT chk_users_phone CHECK (phone_number IS NULL OR phone_number ~ '^\\+?[0-9 ()-]{7,20}$'), 
	UNIQUE (email), 
	UNIQUE (referral_code), 
	FOREIGN KEY(referred_by) REFERENCES users (id) ON DELETE SET NULL
);
""")
        op.execute("""\
CREATE INDEX idx_users_referred_by ON users (referred_by);
CREATE UNIQUE INDEX uq_users_email_lower ON users (lower(email));
""")
        op.execute("""\
CREATE TABLE audit_log (
	id SERIAL NOT NULL, 
	actor_user_id UUID, 
	actor_kind VARCHAR(20) NOT NULL, 
	action VARCHAR(60) NOT NULL, 
	entity_type VARCHAR(40) NOT NULL, 
	entity_id VARCHAR(64) NOT NULL, 
	detail JSONB DEFAULT '{}'::jsonb NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(actor_user_id) REFERENCES users (id) ON DELETE SET NULL
);
""")
        op.execute("""\
CREATE INDEX idx_audit_entity ON audit_log (entity_type, entity_id);
""")
        op.execute("""\
CREATE INDEX idx_audit_actor ON audit_log (actor_user_id, created_at);
""")
        op.execute("""\
CREATE TABLE offers (
	id UUID NOT NULL, 
	owner_id UUID, 
	merchant_name VARCHAR(80) NOT NULL, 
	merchant_address VARCHAR(140), 
	title VARCHAR(120) NOT NULL, 
	description TEXT NOT NULL, 
	category VARCHAR(40) NOT NULL, 
	cashback_cents BIGINT NOT NULL, 
	budget_cents BIGINT NOT NULL, 
	reserved_cents BIGINT DEFAULT 0 NOT NULL, 
	spent_cents BIGINT DEFAULT 0 NOT NULL, 
	min_purchase_cents BIGINT DEFAULT 0 NOT NULL, 
	per_user_limit SMALLINT DEFAULT 1 NOT NULL, 
	starts_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	ends_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	active BOOLEAN DEFAULT true NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT chk_offers_window CHECK (ends_at > starts_at), 
	CONSTRAINT chk_offers_cashback CHECK (cashback_cents BETWEEN 1 AND 5000), 
	CONSTRAINT chk_offers_min_purchase CHECK (min_purchase_cents BETWEEN 0 AND 10000000), 
	CONSTRAINT chk_offers_per_user_limit CHECK (per_user_limit BETWEEN 1 AND 100), 
	CONSTRAINT chk_offers_budget CHECK (reserved_cents + spent_cents <= budget_cents), 
	CONSTRAINT chk_offers_budget_positive CHECK (budget_cents > 0), 
	FOREIGN KEY(owner_id) REFERENCES users (id) ON DELETE SET NULL
);
""")
        op.execute("""\
CREATE INDEX idx_offers_owner ON offers (owner_id);
""")
        op.execute("""\
CREATE INDEX idx_offers_browse ON offers (active, ends_at);
""")
        op.execute("""\
CREATE TABLE password_reset_tokens (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	token_hash VARCHAR(64) NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	used_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	UNIQUE (token_hash)
);
""")
        op.execute("""\
CREATE INDEX idx_prt_user ON password_reset_tokens (user_id, created_at);
""")
        op.execute("""\
CREATE TABLE payouts (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	method payout_method NOT NULL, 
	upi_id VARCHAR(100), 
	amount_cents BIGINT NOT NULL, 
	status payout_status DEFAULT 'REQUESTED' NOT NULL, 
	payment_reference VARCHAR(64), 
	note VARCHAR(200), 
	requested_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	settled_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT chk_payouts_amount CHECK (amount_cents > 0), 
	CONSTRAINT chk_payouts_upi_pairing CHECK ((method = 'UPI') = (upi_id IS NOT NULL)), 
	CONSTRAINT chk_payouts_paid_reference CHECK ((status = 'PAID') = (payment_reference IS NOT NULL)), 
	CONSTRAINT chk_payouts_cancel_note CHECK ((status = 'CANCELLED') = (note IS NOT NULL)), 
	CONSTRAINT chk_payouts_settled_pairing CHECK ((status = 'REQUESTED') = (settled_at IS NULL)), 
	CONSTRAINT chk_payouts_upi_format CHECK (upi_id IS NULL OR upi_id ~ '^[a-zA-Z0-9._-]{2,255}@[a-zA-Z][a-zA-Z0-9-]{1,61}[a-zA-Z]$'), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT
);
""")
        op.execute("""\
CREATE INDEX idx_payouts_user_requested ON payouts (user_id, requested_at);
""")
        op.execute("""\
CREATE UNIQUE INDEX uq_payouts_reference_paid ON payouts (payment_reference) WHERE status = 'PAID';
""")
        op.execute("""\
CREATE UNIQUE INDEX uq_payouts_one_open ON payouts (user_id) WHERE status = 'REQUESTED';
""")
        op.execute("""\
CREATE INDEX idx_payouts_open ON payouts (status) WHERE status = 'REQUESTED';
""")
        op.execute("""\
CREATE TABLE push_subscriptions (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	endpoint TEXT NOT NULL, 
	p256dh VARCHAR(256) NOT NULL, 
	auth_key VARCHAR(256) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	UNIQUE (endpoint)
);
""")
        op.execute("""\
CREATE INDEX idx_push_user ON push_subscriptions (user_id);
""")
        op.execute("""\
CREATE TABLE referral_bonuses (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	amount_cents BIGINT NOT NULL, 
	reason referral_reason NOT NULL, 
	counterpart_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT chk_referral_amount CHECK (amount_cents > 0), 
	CONSTRAINT uq_referral_pair UNIQUE (user_id, counterpart_id, reason), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(counterpart_id) REFERENCES users (id) ON DELETE RESTRICT
);
""")
        op.execute("""\
CREATE INDEX idx_referral_user ON referral_bonuses (user_id, created_at);
""")
        op.execute("""\
CREATE TABLE sessions (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	token_hash VARCHAR(64) NOT NULL, 
	user_agent TEXT, 
	ip_address VARCHAR(64), 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	revoked_at TIMESTAMP WITH TIME ZONE, 
	last_used_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	UNIQUE (token_hash)
);
""")
        op.execute("""\
CREATE INDEX idx_sessions_user_active ON sessions (user_id) WHERE revoked_at IS NULL;
""")
        op.execute("""\
CREATE TABLE support_requests (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	topic support_topic NOT NULL, 
	message VARCHAR(2000) NOT NULL, 
	status support_status DEFAULT 'OPEN' NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
""")
        op.execute("""\
CREATE INDEX idx_support_status ON support_requests (status, created_at);
""")
        op.execute("""\
CREATE INDEX idx_support_user ON support_requests (user_id, created_at);
""")
        op.execute("""\
CREATE TABLE todos (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	due_on DATE NOT NULL, 
	completed BOOLEAN DEFAULT false NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
""")
        op.execute("""\
CREATE INDEX idx_todos_user_due ON todos (user_id, due_on);
""")
        op.execute("""\
CREATE TABLE user_roles (
	user_id UUID NOT NULL, 
	role admin_role NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (user_id, role), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
""")
        op.execute("""\
CREATE TABLE wallet_ledger (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	entry_type ledger_entry_type NOT NULL, 
	amount_cents BIGINT NOT NULL, 
	source_id UUID, 
	reference_key VARCHAR(120) NOT NULL, 
	description VARCHAR(200), 
	transaction_id UUID, 
	reversal_of UUID, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT chk_ledger_sign_rules CHECK ((entry_type = 'REVERSAL' AND amount_cents < 0 AND reversal_of IS NOT NULL) OR (entry_type <> 'REVERSAL' AND amount_cents > 0 AND reversal_of IS NULL)), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT, 
	UNIQUE (reference_key)
);
""")
        op.execute("""\
CREATE INDEX idx_ledger_user_created ON wallet_ledger (user_id, created_at);
""")
        op.execute("""\
CREATE TABLE payout_entries (
	ledger_id UUID NOT NULL, 
	payout_id UUID NOT NULL, 
	PRIMARY KEY (ledger_id), 
	FOREIGN KEY(ledger_id) REFERENCES wallet_ledger (id) ON DELETE CASCADE, 
	FOREIGN KEY(payout_id) REFERENCES payouts (id) ON DELETE CASCADE
);
""")
        op.execute("""\
CREATE INDEX idx_payout_entries_payout ON payout_entries (payout_id);
""")
        op.execute("""\
CREATE TABLE receipts (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	offer_id UUID NOT NULL, 
	merchant_name VARCHAR(80) NOT NULL, 
	purchase_date DATE NOT NULL, 
	total_cents BIGINT NOT NULL, 
	receipt_number VARCHAR(40) NOT NULL, 
	card_last4 VARCHAR(4), 
	fingerprint TEXT NOT NULL, 
	status receipt_status DEFAULT 'SUBMITTED' NOT NULL, 
	cashback_cents BIGINT DEFAULT 0 NOT NULL, 
	rejection_reason TEXT, 
	submitted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	decided_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT chk_receipts_total CHECK (total_cents > 0 AND total_cents <= 10000000), 
	CONSTRAINT chk_receipts_card_last4 CHECK (card_last4 IS NULL OR card_last4 ~ '^[0-9]{4}$'), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(offer_id) REFERENCES offers (id) ON DELETE RESTRICT
);
""")
        op.execute("""\
CREATE INDEX idx_receipts_user_submitted ON receipts (user_id, submitted_at);
""")
        op.execute("""\
CREATE INDEX idx_receipts_offer_status ON receipts (offer_id, status);
""")
        op.execute("""\
CREATE UNIQUE INDEX uq_receipts_fingerprint_live ON receipts (fingerprint) WHERE status <> 'REJECTED';
""")
        op.execute("""\
CREATE TABLE saved_offers (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	offer_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_saved_offers UNIQUE (user_id, offer_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(offer_id) REFERENCES offers (id) ON DELETE CASCADE
);
""")
        op.execute("""\
CREATE INDEX idx_saved_offers_offer ON saved_offers (offer_id);
""")
        op.execute("""\
CREATE TABLE notifications (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	kind notification_kind NOT NULL, 
	receipt_id UUID NOT NULL, 
	merchant_name VARCHAR(80) NOT NULL, 
	cashback_cents BIGINT NOT NULL, 
	read_at TIMESTAMP WITH TIME ZONE, 
	pushed_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_notifications_receipt_kind UNIQUE (receipt_id, kind), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(receipt_id) REFERENCES receipts (id) ON DELETE CASCADE
);
""")
        op.execute("""\
CREATE INDEX idx_notifications_user ON notifications (user_id, created_at);
""")


def downgrade() -> None:
    pass
