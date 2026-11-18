"""Emit PostgreSQL DDL (enums, tables, indexes) from the models, for the
initial Alembic migration and for verifying compilation."""
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from src.db.models import Base

ENUMS = {
    "user_account_type": ["shopper", "retailer"],
    "user_role": ["shopper", "retailer", "admin", "super_admin"],
    "receipt_status": ["SUBMITTED", "REVIEWING", "APPROVED", "PAID", "REJECTED", "REVERSED"],
    "ledger_entry_type": ["RECEIPT_CASHBACK", "REFERRAL_BONUS", "REVERSAL"],
    "payout_method": ["UPI", "CASH"],
    "payout_status": ["REQUESTED", "PAID", "CANCELLED"],
    "referral_reason": ["INVITE_ACCEPTED", "INVITE_SENT"],
    "notification_kind": ["RECEIPT_APPROVED", "RECEIPT_REJECTED"],
    "support_topic": ["ACCOUNT", "CASHBACK", "OFFERS", "OTHER"],
    "support_status": ["OPEN", "ANSWERED", "CLOSED"],
}


def enum_ddl() -> list[str]:
    out = []
    for name, values in ENUMS.items():
        vals = ", ".join(f"'{v}'" for v in values)
        out.append(
            f"DO $$ BEGIN CREATE TYPE {name} AS ENUM ({vals}); "
            f"EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
        )
    return out


def table_ddl() -> list[str]:
    out = []
    for table in Base.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(dialect=postgresql.dialect())).strip() + ";"
        out.append(ddl)
        for index in table.indexes:
            out.append(str(CreateIndex(index).compile(dialect=postgresql.dialect())).strip() + ";")
    return out


if __name__ == "__main__":
    for stmt in enum_ddl() + table_ddl():
        print(stmt)
