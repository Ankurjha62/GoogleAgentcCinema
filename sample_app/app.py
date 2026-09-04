"""Sample app under test for TestMind.

A small FastAPI "e-commerce" service that produces metrics/logs/traces so the
Grafana agents have something real to query. Matches the endpoint contract the
agents assume (http://localhost:8000).

Run:  uvicorn sample_app.app:app --port 8000
"""
from __future__ import annotations

import logging
import random
import time
import uuid
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sample_app")

app = FastAPI(title="TestMind Sample Shop")

PRODUCTS: dict[str, dict] = {
    "p1": {"id": "p1", "name": "TestMind Mug", "price": 14.99, "stock": 42},
    "p2": {"id": "p2", "name": "TestMind Hoodie", "price": 49.99, "stock": 7},
    "p3": {"id": "p3", "name": "TestMind Sticker Pack", "price": 4.99, "stock": 300},
}

_carts: dict[str, dict] = {}
_orders: dict[str, dict] = {}


def _now_ns() -> int:
    return time.time_ns()


@app.middleware("http")
async def _trace_and_count(request, call_next):
    start = _now_ns()
    response = await call_next(request)
    duration_ms = (time.time_ns() - start) / 1e6
    # Emit a log line the agent can find via LogQL later.
    logger.info(
        "request path=%s method=%s status=%d duration_ms=%.1f",
        request.url.path,
        request.method,
        response.status_code,
        duration_ms,
    )
    return response


@app.get("/health")
def health():
    return {"status": "ok", "service": "sample-shop"}


@app.get("/products")
def list_products():
    return list(PRODUCTS.values())


@app.get("/products/{product_id}")
def get_product(product_id: str):
    product = PRODUCTS.get(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")
    return product


class CartItem(BaseModel):
    product_id: str
    qty: int = 1


@app.post("/cart")
def add_to_cart(item: CartItem):
    cart_id = "cart-1"
    product = PRODUCTS.get(item.product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")
    if item.qty <= 0:
        raise HTTPException(status_code=400, detail="qty must be positive")
    if item.qty > product["stock"]:
        raise HTTPException(status_code=409, detail="insufficient stock")
    cart = _carts.setdefault(cart_id, {"items": []})
    cart["items"].append(item.model_dump())
    return {"cart_id": cart_id, "items": cart["items"]}


@app.get("/cart")
def get_cart():
    return _carts.get("cart-1", {"items": []})


class Checkout(BaseModel):
    coupon_code: Optional[str] = None


@app.post("/checkout")
def checkout(payload: Checkout):
    cart = _carts.get("cart-1", {"items": []})
    if not cart["items"]:
        raise HTTPException(status_code=400, detail="cart is empty")
    if payload.coupon_code:
        # Simulated flaky coupon validation (demo hook for self-healing).
        if payload.coupon_code.lower() not in ("testmind10", "free"):
            logger.error("invalid coupon rejected: %s", payload.coupon_code)
            raise HTTPException(status_code=422, detail="invalid coupon code")
    order_id = str(uuid.uuid4())[:8]
    order = {
        "id": order_id,
        "status": "created",
        "items": cart["items"],
        "total": sum(PRODUCTS[i["product_id"]]["price"] * i["qty"] for i in cart["items"]),
    }
    _orders[order_id] = order
    _carts["cart-1"] = {"items": []}
    return {"order_id": order_id, "status": order["status"], "total": order["total"]}


@app.get("/orders")
def list_orders():
    return list(_orders.values())


@app.get("/orders/{order_id}")
def get_order(order_id: str):
    order = _orders.get(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    return order