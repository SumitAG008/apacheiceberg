import datetime
import uuid
import asyncio
from typing import Dict, Any, List, Set, Optional
from pydantic import BaseModel

class TrafficEvent(BaseModel):
    id: str
    timestamp: str
    type: str  # "http_request" or "tool_call"
    method: Optional[str] = None
    path: Optional[str] = None
    status: Optional[str] = None  # e.g. "200" or "success" / "error"
    latency_ms: float
    request_body: Optional[str] = None
    response_body: Optional[str] = None
    tool_name: Optional[str] = None
    tool_args: Optional[str] = None
    tool_result: Optional[str] = None
    parent_id: Optional[str] = None

class TrafficBus:
    _instance: Optional['TrafficBus'] = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(TrafficBus, cls).__new__(cls, *args, **kwargs)
            cls._instance.subscribers = set()
            cls._instance.history = []
            cls._instance.max_history = 500
            cls._instance.lock = asyncio.Lock()
        return cls._instance

    def register(self, queue: asyncio.Queue):
        self.subscribers.add(queue)

    def unregister(self, queue: asyncio.Queue):
        if queue in self.subscribers:
            self.subscribers.remove(queue)

    async def publish(self, event: TrafficEvent):
        async with self.lock:
            # Append to buffer
            self.history.append(event)
            if len(self.history) > self.max_history:
                self.history.pop(0)
            
            # Broadcast to active WebSockets
            if self.subscribers:
                event_dict = event.dict()
                for q in list(self.subscribers):
                    try:
                        await q.put(event_dict)
                    except Exception:
                        pass

    async def get_recent(self) -> List[TrafficEvent]:
        async with self.lock:
            return list(self.history)

# Global singleton
traffic_bus = TrafficBus()
