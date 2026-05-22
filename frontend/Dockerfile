FROM public.ecr.aws/docker/library/python:3.11-slim

WORKDIR /app

# Fix: path relative to repo root (build context is .)
COPY frontend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy frontend app code
COPY frontend/ .

EXPOSE 8501

CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]