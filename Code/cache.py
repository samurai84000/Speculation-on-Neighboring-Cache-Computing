from cache_state import CacheState


class CacheLine:
    def __init__(self, address=None, data=None, state=CacheState.INVALID, version=0):
        self.address = address
        self.data = data
        self.state = state
        self.version = version

    def is_valid(self):
        return self.state != CacheState.INVALID

    def __repr__(self):
        return (
            f"CacheLine(address={self.address}, "
            f"data={self.data}, "
            f"state={self.state.value}, "
            f"version={self.version})"
        )


class Cache:
    def __init__(self, size=16):
        self.size = size
        self.lines = {}

    def contains_valid_block(self, address):
        return address in self.lines and self.lines[address].is_valid()

    def read(self, address):
        if self.contains_valid_block(address):
            return self.lines[address].data
        return None

    def write(self, address, data, state=CacheState.MODIFIED, version=0):
        if len(self.lines) >= self.size and address not in self.lines:
            self.evict_line()

        self.lines[address] = CacheLine(
            address=address,
            data=data,
            state=state,
            version=version
        )

    def invalidate(self, address):
        """
        Returns True only if a valid line was actually invalidated.
        """
        if address in self.lines and self.lines[address].is_valid():
            self.lines[address].state = CacheState.INVALID
            return True

        return False

    def get_line(self, address):
        return self.lines.get(address, None)

    def evict_line(self):
        for address, line in list(self.lines.items()):
            if not line.is_valid():
                del self.lines[address]
                return

        first_address = next(iter(self.lines))
        del self.lines[first_address]

    def __repr__(self):
        return f"Cache(size={self.size}, lines={self.lines})"