"""Idempotency-Key support for mutating financial endpoints.

The first request with a key stores its response; replays with the same key and body return that
response; a replay with a different body is rejected. The unique (household_id, key) constraint makes
this safe under concurrency: a racing duplicate fails to insert and is told to retry.
"""
import hashlib
import json
from collections.abc import Callable

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.deps import Ctx
from app.core.errors import Conflict
from app.models import IdempotencyKey


def run_idempotent(ctx: Ctx, key: str | None, method: str, path: str, payload, fn: Callable[[], object]):
    if not key:
        return fn()
    if len(key) > 128:
        raise Conflict("Idempotency-Key too long", code="idempotency_key_invalid")
    req_hash = hashlib.sha256(json.dumps(jsonable_encoder(payload), sort_keys=True).encode()).hexdigest()
    existing = ctx.db.scalars(
        select(IdempotencyKey).where(IdempotencyKey.household_id == ctx.household_id, IdempotencyKey.key == key)
    ).first()
    if existing:
        if existing.request_hash != req_hash or existing.path != path:
            raise Conflict("Idempotency-Key was already used with a different request", code="idempotency_key_reused")
        if existing.response_body is None:
            raise Conflict("A request with this Idempotency-Key is still in progress", code="idempotency_in_progress")
        return existing.response_body
    record = IdempotencyKey(
        household_id=ctx.household_id, user_id=ctx.user.id, key=key, method=method, path=path, request_hash=req_hash
    )
    ctx.db.add(record)
    try:
        ctx.db.flush()
    except IntegrityError:
        ctx.db.rollback()
        raise Conflict("A request with this Idempotency-Key is already being processed", code="idempotency_in_progress")
    result = jsonable_encoder(fn())
    record.response_status = 200
    record.response_body = result
    ctx.db.commit()
    return result
