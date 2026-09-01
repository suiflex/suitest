# Streamable-HTTP MCP relay for Suitest.
#
# Suitest's own MCP server (@suiflex/suitest-mcp) speaks only stdio. This image
# wraps it behind mcp-proxy (sparfenyuk), which exposes the same tools over the
# Streamable HTTP transport at /mcp, so remote MCP clients can drive Suitest
# over HTTPS (Caddy → mcpsui.keton.id/mcp → this container → stdio).
#
# The relay delegates to the Suitest API over the internal docker network
# (SUITEST_API_URL=http://api:4000) and authenticates with a Suitest API key
# (SUITEST_API_KEY). Clients must present the relay bearer token
# (MCP_RELAY_TOKEN) via the X-API-Key header.
#
# Requires Python >= 3.11 on PATH for the suitest lifecycle server; bookworm
# ships python3.11.
FROM node:22-bookworm-slim

# Python ≥3.11 runtime for the suitest lifecycle server (bookworm ships 3.11),
# plus pip and the black-box tooling dependencies baked in at build time:
# suitest_lifecycle can pip-install playwright on demand, but bookworm-slim
# python3 has neither pip nor ensurepip, and a runtime
# `playwright install chromium` would still miss the chromium OS libraries.
# requests is preinstalled for orchestrator.py's pydeps.ensure("requests").
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip ca-certificates \
    && pip install --no-cache-dir --break-system-packages playwright requests \
    && python3 -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g mcp-proxy @suiflex/suitest-mcp@latest

# The spawned child (suitest-mcp) inherits this process's environment, so
# SUITEST_API_URL / SUITEST_API_KEY / MCP_RELAY_TOKEN reach it via compose env.
EXPOSE 4044
# Shell form so the container shell expands ${MCP_RELAY_TOKEN} from its env at
# runtime (compose writes a literal $${...} here after its own interpolation).
ENTRYPOINT []
CMD ["sh", "-c", "mcp-proxy --host 0.0.0.0 --port 4044 --streamEndpoint /mcp --apiKey \"${MCP_RELAY_TOKEN}\" -- suitest-mcp"]
