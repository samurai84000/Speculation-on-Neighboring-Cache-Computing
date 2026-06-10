from cache_state import CacheState


class CacheController:
    def __init__(self, node_id, cache):
        self.node_id = node_id
        self.cache = cache
        self.node = None

        self.stats = {
            "local_hits": 0,
            "local_misses": 0,
            "writes": 0,
            "invalidations": 0,
            "speculative_hits": 0,
            "speculative_failures": 0,
            "speculative_successes": 0,
        }

    def attach_node(self, node):
        self.node = node

    def read_request(self, address):
        if self.cache.contains_valid_block(address):
            self.stats["local_hits"] += 1
            return self.cache.read(address)

        self.stats["local_misses"] += 1
        print(f"Node {self.node_id}: cache miss on address {address}")
        return None

    def write_request(self, address, data):
        self.stats["writes"] += 1

        self.cache.write(
            address=address,
            data=data,
            state=CacheState.MODIFIED
        )

    def receive_invalidation(self, address):
        self.stats["invalidations"] += 1
        self.cache.invalidate(address)

    def __repr__(self):
        return f"CacheController(node_id={self.node_id}, stats={self.stats})"