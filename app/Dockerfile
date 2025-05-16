FROM python:3.9-slim

WORKDIR /app
COPY . /app

# Update pip and install dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

CMD ["python", "wsgi.py"]