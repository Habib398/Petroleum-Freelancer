from __future__ import annotations

from flask import has_request_context, session

VALID_BRANDS = ("consulting", "petroleum")

def get_brand(default: str = "consulting") -> str:
    fallback = (default or "consulting").strip().lower()
    if fallback not in VALID_BRANDS:
        fallback = "consulting"
    if not has_request_context():
        return fallback
    b = (session.get("brand") or fallback).strip().lower()
    return b if b in VALID_BRANDS else fallback

def set_brand(brand: str) -> str:
    b = (brand or "").strip().lower()
    if b not in VALID_BRANDS:
        b = "consulting"
    session["brand"] = b
    return b

def parse_allowed_brands(value: str | None) -> set[str]:
    if not value:
        return {"consulting"}
    parts = [p.strip().lower() for p in value.split(",") if p.strip()]
    allowed = {p for p in parts if p in VALID_BRANDS}
    return allowed or {"consulting"}

def user_allows_brand(user: dict | None, brand: str) -> bool:
    if not user:
        return False
    allowed = parse_allowed_brands(user.get("allowed_brands") if isinstance(user, dict) else None)
    return brand in allowed
