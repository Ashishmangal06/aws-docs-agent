FROM public.ecr.aws/docker/library/python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy entire backend folder contents into /app/backend/
# This preserves the 'backend' package name for imports
COPY backend/ ./backend/

# Create data directory for FAISS index
RUN mkdir -p /app/data/faiss_index

EXPOSE 8000

# Now 'backend.app.main' resolves correctly from /app
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]