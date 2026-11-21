# syntax=docker/dockerfile:1.7

FROM ghcr.io/gitleaks/gitleaks:v8.30.1 AS gitleaks

FROM node:20-bookworm-slim AS node-runtime

FROM python:3.11-slim-bookworm

ARG DEBIAN_FRONTEND=noninteractive

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        build-essential \
        ca-certificates \
        curl \
        docker.io \
        git \
        maven \
        openjdk-17-jdk-headless \
        openssh-client \
        tini \
        unzip \
    && rm -rf /var/lib/apt/lists/*

# Install the Compose CLI plugin as well as docker.io. Deployment uses docker compose.
ARG DOCKER_COMPOSE_VERSION=v5.4.0
RUN set -eu; \
    arch="$(uname -m)"; \
    mkdir -p /usr/local/lib/docker/cli-plugins; \
    cd /tmp; \
    curl -fsSLO "https://github.com/docker/compose/releases/download/${DOCKER_COMPOSE_VERSION}/docker-compose-linux-${arch}"; \
    curl -fsSLO "https://github.com/docker/compose/releases/download/${DOCKER_COMPOSE_VERSION}/docker-compose-linux-${arch}.sha256"; \
    sha256sum -c "docker-compose-linux-${arch}.sha256"; \
    install -m 0755 "docker-compose-linux-${arch}" /usr/local/lib/docker/cli-plugins/docker-compose; \
    rm "docker-compose-linux-${arch}" "docker-compose-linux-${arch}.sha256"; \
    docker compose version

COPY --from=gitleaks /usr/bin/gitleaks /usr/local/bin/gitleaks
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/lib/node_modules/ /usr/local/lib/node_modules/

RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && ln -s ../lib/node_modules/corepack/dist/corepack.js /usr/local/bin/corepack \
    && corepack enable \
    && node --version \
    && npm --version \
    && corepack --version

RUN curl -fsSL https://services.gradle.org/distributions/gradle-8.7-bin.zip \
    -o /tmp/gradle.zip \
    && unzip -q /tmp/gradle.zip -d /opt \
    && ln -s /opt/gradle-8.7/bin/gradle /usr/local/bin/gradle \
    && rm /tmp/gradle.zip \
    && gradle --version

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/runs /app/workspace \
    && gitleaks version \
    && semgrep --version \
    && python -m compileall -q app main.py

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "app.poller"]
