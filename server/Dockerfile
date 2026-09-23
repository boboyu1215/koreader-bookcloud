FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd -u 10001 -M bookcloud \
    && mkdir /data && chown 10001:10001 /data && chmod 700 /data
COPY app.py admin.html legado.py source_manager.py ./
USER 10001:10001
ENV BOOKCLOUD_DATA=/data PORT=8080 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "app.py"]
