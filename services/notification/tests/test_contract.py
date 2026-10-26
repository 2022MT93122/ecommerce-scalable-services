from pathlib import Path


def test_service_file_exists():
    source = Path("app/main.py").read_text()
    assert '@app.get("/health")' in source
    assert "app = FastAPI(" in source or "app=FastAPI(" in source
