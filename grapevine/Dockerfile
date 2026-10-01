# AgentCore Runtime image: arm64, MCP over streamable HTTP on :8000/mcp.
# Build from the repository root so upstream's package is in the context:
#   docker buildx build --platform linux/arm64 -f grapevine/Dockerfile .
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first so code-only changes reuse the cached layer.
COPY pyproject.toml README.md LICENSE ./
COPY analytics_mcp ./analytics_mcp
COPY grapevine/requirements.txt ./grapevine/requirements.txt
RUN pip install . -r grapevine/requirements.txt

COPY grapevine ./grapevine

RUN useradd --uid 1000 --no-create-home --shell /usr/sbin/nologin app
USER app

EXPOSE 8000
CMD ["python", "-m", "grapevine.agentcore_server"]
