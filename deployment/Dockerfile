FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY data ./data
RUN useradd --create-home --uid 10001 uc1 && mkdir /state && chown uc1:uc1 /state
USER uc1
ENV UC1_STORAGE_ROOT=/state PYTHONUNBUFFERED=1
EXPOSE 8000
# One worker owns the in-memory LangGraph checkpoints and run registry.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
