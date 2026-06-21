FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml ./
COPY custodian/ custodian/

RUN pip install --no-cache-dir .

CMD ["custodian", "--help"]
