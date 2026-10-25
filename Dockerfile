FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/
ENV PORT=8002
ENV HOST=0.0.0.0
ENV DB_PATH=/app/inventory.db
ENV SERVICE_NAME=inventory-service
EXPOSE 8002
CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8002"]