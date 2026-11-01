"""Checkout orchestration. All downstream access is through HTTP."""
import os
import random
import time
import json
import httpx
from .common import logger

INVENTORY = os.getenv("INVENTORY_URL", "http://localhost:8001")
PAYMENT = os.getenv("PAYMENT_URL", "http://localhost:8003")
NOTIFICATION = os.getenv("NOTIFICATION_URL", "http://localhost:8004")
TIMEOUT = float(os.getenv("PAYMENT_TIMEOUT", "0.7"))


PAYMENT_ATTEMPTS = max(1, int(os.getenv("PAYMENT_ATTEMPTS", "3")))
RETRY_BACKOFF = max(0.0, float(os.getenv("RETRY_BACKOFF", "0.1")))
REPLAY_WAIT = max(0.0, float(os.getenv("REPLAY_WAIT", "10")))
TERMINAL_STATES = {"CONFIRMED", "FAILED", "OUT_OF_STOCK"}
ALLOWED_TRANSITIONS = {
    "PENDING": {"INVENTORY_PENDING", "PAYMENT_PENDING", "OUT_OF_STOCK"},
    "INVENTORY_PENDING": {"PAYMENT_PENDING", "OUT_OF_STOCK"},
    "PAYMENT_PENDING": {"STOCK_CONFIRM_PENDING", "CONFIRMED", "RELEASE_PENDING", "FAILED"},
    "STOCK_CONFIRM_PENDING": {"CONFIRMED"},
    "RELEASE_PENDING": {"FAILED"},
}


def transition(order, state):
    if state != order.status and state not in ALLOWED_TRANSITIONS.get(order.status, set()):
        raise ValueError(f"Invalid order transition: {order.status} -> {state}")
    order.status = state


def payment_outcome(response):
    status = response.json()["status"]
    if status not in {"SUCCEEDED", "DECLINED"}:
        raise ValueError("Unknown payment outcome")
    return status


def snapshot(o):
    return {"order_id": o.id, "status": o.status, "hold_id": o.hold_id}


def downstream(method, url, request_id, **kwargs):
    headers = {"X-Request-ID": request_id, **kwargs.pop("headers", {})}
    with httpx.Client(timeout=TIMEOUT) as client:
        return client.request(method, url, headers=headers, **kwargs)


def confirm_stock(order, request_id):
    r = downstream("POST", f"{INVENTORY}/api/v1/stock/{order.hold_id}/confirm", request_id)
    r.raise_for_status()


def notify_best_effort(order, request_id):
    try:
        downstream(
            "POST",
            f"{NOTIFICATION}/api/v1/notifications",
            request_id,
            json={
                "order_id": order.id,
                "recipient": order.recipient,
                "content": "Your order is confirmed",
            },
        ).raise_for_status()
    except httpx.HTTPError:
        logger.warning(json.dumps({"event": "notification_failed", "order_id": order.id,
                                   "request_id": request_id}))


def finalize(order, db, request_id, payment_status):
    if payment_status == "SUCCEEDED":
        try:
            confirm_stock(order, request_id)
        except httpx.HTTPError:
            transition(order, "STOCK_CONFIRM_PENDING")
            db.commit()
            return
        transition(order, "CONFIRMED")
        db.commit()
        notify_best_effort(order, request_id)
    elif payment_status == "DECLINED":
        try:
            downstream(
                "POST",
                f"{INVENTORY}/api/v1/stock/{order.hold_id}/release",
                request_id,
            ).raise_for_status()
        except httpx.HTTPError:
            transition(order, "RELEASE_PENDING")
            db.commit()
            return
        transition(order, "FAILED")
        db.commit()


def process(order, db, request_id, simulate):
    if order.status in TERMINAL_STATES:
        return
    if order.hold_id is None:
        try:
            r = downstream(
                "POST",
                f"{INVENTORY}/api/v1/stock/reserve",
                request_id,
                json={
                    "order_id": order.id,
                    "product_id": order.product_id,
                    "quantity": order.quantity,
                },
            )
        except httpx.HTTPError:
            transition(order, "INVENTORY_PENDING")
            db.commit()
            return

        if r.status_code == 409:
            transition(order, "OUT_OF_STOCK")
            db.commit()
            return
        if r.status_code != 201:
            transition(order, "INVENTORY_PENDING")
            db.commit()
            return
        try:
            hold_id = r.json()["hold_id"]
            if type(hold_id) is not int or hold_id <= 0:
                raise ValueError("Invalid hold ID")
        except (ValueError, KeyError, TypeError):
            transition(order, "INVENTORY_PENDING")
            db.commit()
            return
        order.hold_id = hold_id
        transition(order, "PAYMENT_PENDING")
        db.commit()

    payload = {
        "order_id": order.id,
        "amount_cents": order.amount_cents,
        "simulate": simulate,
    }
    for i in range(PAYMENT_ATTEMPTS):
        try:
            r = downstream(
                "POST",
                f"{PAYMENT}/api/v1/payments",
                request_id,
                json=payload,
                headers={"Idempotency-Key": "pay-" + order.id},
            )
            r.raise_for_status()
            finalize(order, db, request_id, payment_outcome(r))
            return
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            logger.warning(json.dumps({"event": "payment_attempt_failed", "order_id": order.id,
                                       "attempt": i + 1, "request_id": request_id}))
            if i < PAYMENT_ATTEMPTS - 1:
                time.sleep(RETRY_BACKOFF * (2**i) + random.uniform(0, RETRY_BACKOFF))

    try:
        r = downstream(
            "GET",
            f"{PAYMENT}/api/v1/payments/by-key/pay-{order.id}",
            request_id,
        )
        if r.status_code == 200:
            finalize(order, db, request_id, payment_outcome(r))
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        logger.warning(json.dumps({"event": "payment_pending", "order_id": order.id,
                                   "request_id": request_id}))



def reconcile(order, db, request_id):
    """Advance pending work; retain the original POST response for replay."""
    from .models import CheckoutRecord

    record = db.get(CheckoutRecord, order.id)
    if order.status in {"PENDING", "INVENTORY_PENDING"}:
        if record is not None:
            process(order, db, request_id, record.simulate)
    elif order.status == "STOCK_CONFIRM_PENDING":
        finalize(order, db, request_id, "SUCCEEDED")
    elif order.status == "RELEASE_PENDING":
        finalize(order, db, request_id, "DECLINED")
    elif order.status == "PAYMENT_PENDING":
        try:
            result = downstream("GET", f"{PAYMENT}/api/v1/payments/by-key/pay-{order.id}", request_id)
            if result.status_code == 200:
                finalize(order, db, request_id, payment_outcome(result))
            elif result.status_code == 404 and record is not None:
                process(order, db, request_id, record.simulate)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            logger.warning(json.dumps({"event": "reconciliation_pending", "order_id": order.id,
                                       "request_id": request_id}))
    # A crash before saving the initial response should not leave replays waiting forever.
    if record is not None and record.response is None:
        record.response = snapshot(order)
        db.commit()
