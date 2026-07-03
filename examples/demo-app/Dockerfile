FROM python:3.12-slim

WORKDIR /srv/brewly

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY static ./static

EXPOSE 8089

HEALTHCHECK --interval=5s --timeout=3s --retries=10 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8089/health')"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8089"]
