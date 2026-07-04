"""WebSocket gateway — JWT-authenticated `/ws` endpoint + Redis pub/sub bridge.

The gateway accepts the FastAPI-Users JWT via a ``?token=`` query param (cookies
do not survive the cross-origin WS upgrade reliably), validates it via the same
``JWTStrategy`` used for HTTP cookie auth, then maintains a per-connection set
of subscribed Redis channels. A single background task reads every subscribed
channel via ``redis.asyncio.client.PubSub`` and fans out received payloads to
every connection that subscribed to that channel.

Topics produced by the rest of the system today:
* ``run:<id>`` — runner step / log / completion events (Tasks 6, 8, 15)
* ``workspace:<id>`` — workspace-scoped events (mcp.provider.health, capability.changed)

"""
