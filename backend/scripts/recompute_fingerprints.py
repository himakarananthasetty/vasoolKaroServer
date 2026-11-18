"""One-time data step for Supabase import: recompute receipt fingerprints as SHA-256.

The legacy Supabase system stored MD5 fingerprints. This backend hashes the same
five normalized inputs with SHA-256 (see src.claims.service.compute_fingerprint).
Because every fingerprint input is stored on the receipt row, the hash can be
recomputed at import time — no legacy hash needs to be kept or matched.

Run once AFTER receipts are imported and BEFORE duplicate checks are enabled:

    python3 -m scripts.recompute_fingerprints

The partial unique index on non-rejected fingerprints then guards the recomputed
values exactly as it does for new submissions.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date

from sqlalchemy import update
from sqlalchemy.orm import Session

from src.db.models import Receipt

logger = logging.getLogger("vasoolkaro.migration.fingerprints")


def compute_fingerprint(
    merchant_name: str,
    purchase_date: date,
    total_cents: int,
    receipt_number: str,
    card_last4: str | None,
) -> str:
    normalized = "|".join(
        [
            merchant_name.strip().lower(),
            purchase_date.isoformat(),
            str(total_cents),
            receipt_number.strip().lower(),
            (card_last4 or "").strip(),
        ]
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def recompute_all_fingerprints(db: Session) -> int:
    """Recompute SHA-256 fingerprints for every imported receipt. Idempotent."""
    rows = db.query(Receipt).all()
    updated = 0
    for r in rows:
        expected = compute_fingerprint(
            r.merchant_name,
            r.purchase_date,
            int(r.total_cents),
            r.receipt_number,
            r.card_last4,
        )
        if r.fingerprint != expected:
            db.execute(update(Receipt).where(Receipt.id == r.id).values(fingerprint=expected))
            updated += 1
    db.commit()
    logger.info("recomputed %d of %d receipt fingerprints", updated, len(rows))
    return updated


def main() -> None:
    from src.core.db import SessionLocal  # noqa: PLC0415

    with SessionLocal() as db:
        recompute_all_fingerprints(db)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
