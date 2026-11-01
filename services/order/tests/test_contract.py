from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError


def test_health_and_openapi(client):
    assert client.get('/health').json() == {'status': 'ok', 'service': 'order'}
    spec = client.get('/openapi.json').json()
    checkout = spec['paths']['/api/v1/orders']['post']
    assert '202' in checkout['responses']
    assert any(p['name'] == 'Idempotency-Key' and p['required'] for p in checkout['parameters'])


def test_database_unavailable_health(client, monkeypatch):
    def unavailable(*args, **kwargs):
        raise OperationalError('SELECT 1', {}, Exception('database stopped'))
    monkeypatch.setattr(Session, 'execute', unavailable)
    response = client.get('/health', headers={'X-Request-ID': 'health-test'})
    assert response.status_code == 503
    assert response.json()['error']['message'] == 'Database unavailable'
    assert response.json()['request_id'] == 'health-test'
