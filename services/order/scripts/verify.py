"""Run against the existing four-service stack. Requires Order's httpx dependency."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
import uuid

import httpx

INVENTORY = os.getenv('INVENTORY_URL', 'http://localhost:8001')
ORDER = os.getenv('ORDER_URL', 'http://localhost:8002')


def call(method, path, **kwargs):
    response = httpx.request(method, path, timeout=30, **kwargs)
    return response.status_code, response.json()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--payment-outage', action='store_true')
    parser.add_argument('--reconcile', metavar='ORDER_ID')
    args = parser.parse_args()
    print(datetime.now(timezone.utc).isoformat())
    if args.reconcile:
        code, result = call('POST', f'{ORDER}/api/v1/orders/{args.reconcile}/reconcile')
        print('Reconciled:', code, result)
        assert code == 200 and result['status'] == 'CONFIRMED', result
        return
    for simulate in (['success'] if args.payment_outage else ['success', 'decline', 'slow']):
        code, product = call('POST', INVENTORY + '/api/v1/products',
                             json={'name': 'Order verification', 'price_cents': 999, 'available': 5})
        assert code == 201, product
        body = {'product_id': product['id'], 'quantity': 1, 'amount_cents': 999,
                'recipient': 'demo@example.com', 'simulate': simulate}
        headers = {'Idempotency-Key': str(uuid.uuid4()), 'X-Request-ID': 'order-verify-' + str(uuid.uuid4())}
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: call('POST', ORDER + '/api/v1/orders', json=body,
                                                   headers=headers), range(2)))
        print(simulate, 'simultaneous:', results)
        assert results[0] == results[1], results
        code, result = results[0]
        oid = result['order_id']
        if args.payment_outage:
            assert code == 202 and result['status'] == 'PAYMENT_PENDING', results
            print('Restart Payment and run --reconcile', oid)
            return
        assert code == 201 and result['status'] == ('FAILED' if simulate == 'decline' else 'CONFIRMED'), result
        assert call('POST', ORDER + '/api/v1/orders', json=body, headers=headers) == results[0]
        changed_code, changed = call('POST', ORDER + '/api/v1/orders',
                                     json={**body, 'quantity': 2}, headers=headers)
        assert changed_code == 409 and changed['error']['code'] == 'KEY_REUSED', changed
        stock_code, stock = call('GET', INVENTORY + f"/api/v1/products/{product['id']}")
        assert stock_code == 200 and stock['available'] == (5 if simulate == 'decline' else 4), stock
    print('PASS: identical concurrent/replayed checkout, payload conflict, compensation and slow-payment recovery')


if __name__ == '__main__':
    main()
