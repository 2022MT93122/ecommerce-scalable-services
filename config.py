import os
class Settings:
    SERVICE_NAME: str = os.getenv("SERVICE_NAME", "inventory-service")
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8002"))
    DB_PATH: str = os.getenv("DB_PATH", "inventory.db")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
settings = Settings()