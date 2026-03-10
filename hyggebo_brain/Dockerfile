ARG BUILD_FROM
FROM ${BUILD_FROM}

# Install PostgreSQL client libs for asyncpg
RUN apk add --no-cache \
    postgresql-dev \
    gcc \
    musl-dev \
    python3-dev

# Copy requirements and install
COPY requirements.txt /tmp/
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# Copy application
COPY app/ /app/
COPY run.sh /

RUN chmod a+x /run.sh

CMD ["/run.sh"]
