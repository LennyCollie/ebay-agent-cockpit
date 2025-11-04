FROM python:3.11

WORKDIR /workspace

# Nur requirements zuerst kopieren
COPY requirements.txt .

# Dependencies installieren – mit Cache
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Dann erst den Rest des Projekts kopieren
COPY . .

CMD ["python", "app.py"]

