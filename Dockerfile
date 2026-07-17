FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY custodian/ custodian/
COPY paladin/ paladin/
COPY talaria/ talaria/

RUN pip install --no-cache-dir .

CMD ["custodian", "--help"]
