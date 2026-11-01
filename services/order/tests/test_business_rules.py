from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import logic
from app.models import CheckoutRecord, Order

URL = '/api/v1/orders'
BODY = {'product_id': 1, 'quantity': 1, 'amount_cents': 999, 'recipient': 'test@example.com'}
HEADERS = {'Idempotency-Key': 'checkout-1', 'X-Request-ID': 'order-test'}


def reply(method, url, http_status=200, **data):
    return httpx.Response(http_status, json=data, request=httpx.Request(method, url))


@pytest.fixture
def downstream(monkeypatch):
    calls = []
    def send(method, url, rid, **kwargs):
        calls.append((method, url, rid, kwargs))
        if url.endswith('/reserve'):
            return reply(method, url, 201, hold_id=7, status='HELD')
        return reply(method, url, status='SUCCEEDED')
    monkeypatch.setattr(logic, 'downstream', send)
    monkeypatch.setattr(logic, 'RETRY_BACKOFF', 0)
    return calls


def test_br3_replay_one_order(client, database, downstream):
    first = client.post(URL, json=BODY, headers=HEADERS)
    assert first.status_code == 201
    assert first.json()['status'] == 'CONFIRMED'
    count = len(downstream)
    replay = client.post(URL, json=BODY, headers=HEADERS)
    assert replay.status_code == first.status_code and replay.json() == first.json()
    assert len(downstream) == count
    assert all(c[2] == 'order-test' for c in downstream)
    assert first.headers['X-Correlation-ID'] == 'order-test'
    with database() as db:
        assert db.scalar(select(func.count()).select_from(Order)) == 1
        assert db.scalar(select(CheckoutRecord)).response == first.json()


def test_br4_changed_payload(client, downstream):
    client.post(URL, json=BODY, headers=HEADERS)
    r = client.post(URL, json={**BODY, 'quantity': 2}, headers=HEADERS)
    assert r.status_code == 409
    assert r.json()['error']['code'] == 'KEY_REUSED'


@pytest.mark.parametrize('different', [False, True])
def test_concurrent_key_insert(client, database, downstream, monkeypatch, different):
    # Both requests observe no order, forcing the unique-key INSERT race.
    barrier = Barrier(2)
    original = Session.scalar
    def scalar(db, statement, *args, **kwargs):
        result = original(db, statement, *args, **kwargs)
        if not db.info.get('checked'):
            db.info['checked'] = True
            barrier.wait(timeout=5)
        return result
    monkeypatch.setattr(Session, 'scalar', scalar)
    bodies = [BODY, {**BODY, 'quantity': 2} if different else BODY]
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda b: client.post(URL, json=b, headers=HEADERS), bodies))
    monkeypatch.setattr(Session, 'scalar', original)
    if different:
        assert sorted(r.status_code for r in replies) == [201, 409]
    else:
        assert replies[0].status_code == replies[1].status_code == 201
        assert replies[0].json() == replies[1].json()
    assert len([c for c in downstream if c[1].endswith('/reserve')]) == 1
    assert len([c for c in downstream if c[0] == 'POST' and '/payments' in c[1]]) == 1
    with database() as db:
        assert db.scalar(select(func.count()).select_from(Order)) == 1


def test_br6_notification_failure_keeps_paid_order(client, downstream, monkeypatch):
    original = logic.downstream
    def send(method, url, rid, **kwargs):
        if '/notifications' in url:
            return reply(method, url, 503)
        return original(method, url, rid, **kwargs)
    monkeypatch.setattr(logic, 'downstream', send)
    assert client.post(URL, json=BODY, headers=HEADERS).json()['status'] == 'CONFIRMED'


def test_decline_releases_stock(client, downstream, monkeypatch):
    original = logic.downstream
    def send(method, url, rid, **kwargs):
        if '/payments' in url:
            return reply(method, url, 201, status='DECLINED')
        return original(method, url, rid, **kwargs)
    monkeypatch.setattr(logic, 'downstream', send)
    result = client.post(URL, json={**BODY, 'simulate': 'decline'}, headers=HEADERS)
    assert result.json()['status'] == 'FAILED'
    assert any(c[1].endswith('/release') for c in downstream)


@pytest.mark.parametrize('dependency', ['inventory', 'payment'])
@pytest.mark.parametrize('http_error', [False, True])
def test_outage_recovery_preserves_options(client, downstream, monkeypatch, dependency, http_error):
    original = logic.downstream
    target = logic.INVENTORY if dependency == 'inventory' else logic.PAYMENT
    attempts = []
    def stopped(method, url, rid, **kwargs):
        if url.startswith(target):
            attempts.append(method)
            if http_error:
                return reply(method, url, 503)
            raise httpx.ConnectError('service stopped')
        return original(method, url, rid, **kwargs)
    monkeypatch.setattr(logic, 'downstream', stopped)
    body = {**BODY, 'simulate': 'slow'}
    first = client.post(URL, json=body, headers=HEADERS)
    assert first.status_code == 202
    assert first.json()['status'] == ('INVENTORY_PENDING' if dependency == 'inventory' else 'PAYMENT_PENDING')
    if dependency == 'payment':
        assert attempts.count('POST') == logic.PAYMENT_ATTEMPTS
    def recovered(method, url, rid, **kwargs):
        if method == 'GET' and '/payments/by-key' in url:
            return reply(method, url, 404)
        return original(method, url, rid, **kwargs)
    monkeypatch.setattr(logic, 'downstream', recovered)
    oid = first.json()['order_id']
    assert client.post(f'{URL}/{oid}/reconcile').json()['status'] == 'CONFIRMED'
    charges = [c for c in downstream if c[0] == 'POST' and '/payments' in c[1]]
    assert charges[-1][3]['json']['simulate'] == 'slow'
    assert charges[-1][3]['headers']['Idempotency-Key'] == 'pay-' + oid
    # Original POST response remains immutable; GET exposes recovered status.
    assert client.post(URL, json=body, headers=HEADERS).json() == first.json()
    assert client.get(f'{URL}/{oid}').json()['status'] == 'CONFIRMED'


@pytest.mark.parametrize('action,pending', [('confirm', 'STOCK_CONFIRM_PENDING'), ('release', 'RELEASE_PENDING')])
def test_stock_finalization_recovery(client, downstream, monkeypatch, action, pending):
    original = logic.downstream
    def send(method, url, rid, **kwargs):
        if url.endswith('/' + action):
            raise httpx.ConnectError('inventory stopped')
        if action == 'release' and '/payments' in url:
            return reply(method, url, 201, status='DECLINED')
        return original(method, url, rid, **kwargs)
    monkeypatch.setattr(logic, 'downstream', send)
    first = client.post(URL, json=BODY, headers=HEADERS)
    assert first.status_code == 202 and first.json()['status'] == pending
    monkeypatch.setattr(logic, 'downstream', original)
    oid = first.json()['order_id']
    expected = 'CONFIRMED' if action == 'confirm' else 'FAILED'
    assert client.post(f'{URL}/{oid}/reconcile').json()['status'] == expected
    count = len(downstream)
    assert client.post(f'{URL}/{oid}/reconcile').json()['status'] == expected
    assert len(downstream) == count


def test_terminal_transition_rejected():
    with pytest.raises(ValueError, match='Invalid order transition'):
        logic.transition(Order(status='CONFIRMED'), 'PAYMENT_PENDING')


@pytest.mark.parametrize('changes,headers', [
    ({'quantity': 0}, HEADERS), ({'product_id': 0}, HEADERS),
    ({'amount_cents': 0}, HEADERS), ({'simulate': 'unknown'}, HEADERS),
    ({}, {}), ({}, {'Idempotency-Key': ''}),
    ({}, {'Idempotency-Key': 'x' * 121}),
])
def test_validation_errors(client, changes, headers):
    result = client.post(URL, json={**BODY, **changes}, headers=headers)
    assert result.status_code == 422
    assert result.json()['error']['code'] == 'VALIDATION_ERROR'
    assert 'request_id' in result.json()


def test_missing_order(client):
    for result in [client.get(URL + '/missing'), client.post(URL + '/missing/reconcile')]:
        assert result.status_code == 404
        assert set(result.json()) == {'error', 'request_id'}


def test_out_of_stock_does_not_charge(client, downstream, monkeypatch):
    def send(method, url, rid, **kwargs):
        assert url.endswith('/reserve')
        return reply(method, url, 409, detail={'error': {'code': 'OUT_OF_STOCK'}})
    monkeypatch.setattr(logic, 'downstream', send)
    assert client.post(URL, json=BODY, headers=HEADERS).json()['status'] == 'OUT_OF_STOCK'


def test_slow_payment_committed_before_timeout(client, downstream, monkeypatch):
    posts = []
    def send(method, url, rid, **kwargs):
        if '/payments' in url:
            if method == 'POST':
                posts.append(kwargs)
                raise httpx.ReadTimeout('payment may have committed')
            return reply(method, url, status='SUCCEEDED')
        if url.endswith('/reserve'):
            return reply(method, url, 201, hold_id=7)
        return reply(method, url)
    monkeypatch.setattr(logic, 'downstream', send)
    assert client.post(URL, json=BODY, headers=HEADERS).json()['status'] == 'CONFIRMED'
    assert len(posts) == logic.PAYMENT_ATTEMPTS
    assert all(p == posts[0] for p in posts)


@pytest.mark.parametrize('dependency', ['inventory', 'payment'])
def test_malformed_downstream_retains_pending(client, downstream, monkeypatch, dependency):
    original = logic.downstream
    def malformed(method, url, rid, **kwargs):
        if (dependency == 'inventory' and url.endswith('/reserve')) or (dependency == 'payment' and '/payments' in url):
            return reply(method, url, 201, unexpected='payload')
        return original(method, url, rid, **kwargs)
    monkeypatch.setattr(logic, 'downstream', malformed)
    r = client.post(URL, json=BODY, headers=HEADERS)
    assert r.status_code == 202
    assert r.json()['status'] == ('INVENTORY_PENDING' if dependency == 'inventory' else 'PAYMENT_PENDING')


def test_legacy_unknown_payment_is_not_recreated(client, database, monkeypatch):
    with database() as db:
        db.add(Order(id='legacy-order', key='legacy', fingerprint='old-fingerprint', product_id=1,
                     quantity=1, amount_cents=999, recipient='test@example.com',
                     hold_id=7, status='PAYMENT_PENDING'))
        db.commit()
    def lookup_only(method, url, rid, **kwargs):
        assert method == 'GET', 'Cannot reconstruct an old payment payload safely'
        return reply(method, url, 404)
    monkeypatch.setattr(logic, 'downstream', lookup_only)
    result = client.post(URL + '/legacy-order/reconcile')
    assert result.json()['status'] == 'PAYMENT_PENDING'


def test_replay_wait_is_bounded_without_reprocessing(client, database, downstream, monkeypatch):
    first = client.post(URL, json=BODY, headers=HEADERS)
    oid = first.json()['order_id']
    with database() as db:
        record = db.get(CheckoutRecord, oid)
        record.response = None
        order = db.get(Order, oid)
        order.status = 'PENDING'
        order.hold_id = None
        db.commit()
    monkeypatch.setattr(logic, 'REPLAY_WAIT', 0)
    count = len(downstream)
    replay = client.post(URL, json=BODY, headers=HEADERS)
    assert replay.status_code == 202 and replay.json()['order_id'] == oid
    assert len(downstream) == count


def test_retry_backoff_is_exponential_with_jitter(client, downstream, monkeypatch):
    original = logic.downstream
    delays = []
    def stopped(method, url, rid, **kwargs):
        if '/payments' in url:
            raise httpx.ConnectError('stopped')
        return original(method, url, rid, **kwargs)
    monkeypatch.setattr(logic, 'downstream', stopped)
    monkeypatch.setattr(logic, 'PAYMENT_ATTEMPTS', 3)
    monkeypatch.setattr(logic, 'RETRY_BACKOFF', 0.1)
    monkeypatch.setattr(logic.random, 'uniform', lambda a, b: b / 2)
    monkeypatch.setattr(logic.time, 'sleep', delays.append)
    assert client.post(URL, json=BODY, headers=HEADERS).status_code == 202
    assert delays == pytest.approx([0.15, 0.25])
