from enum import Enum


class CacheState(Enum):
    INVALID = "I"
    SHARED = "S"
    EXCLUSIVE = "E"
    MODIFIED = "M"