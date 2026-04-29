"""Application-wide rate limiter (in-memory)."""
from slowapi import Limiter
from slowapi.util import get_remote_address

# In-memory storage is fine for a single-instance deployment. For multi-worker
# / multi-pod, point storage_uri at Redis: `Limiter(..., storage_uri="redis://...")`.
limiter = Limiter(key_func=get_remote_address, default_limits=[])
