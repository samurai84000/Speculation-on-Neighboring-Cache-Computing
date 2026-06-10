from processor import Processor
from cache import Cache
from cache_controller import CacheController


class Node:
    def __init__(self, node_id, cache_size=16):
        self.node_id = node_id

        self.processor = Processor(processor_id=node_id)
        self.cache = Cache(size=cache_size)
        self.cache_controller = CacheController(
            node_id=node_id,
            cache=self.cache
        )

        self.cache_controller.attach_node(self)

        self.neighbors = []

    def add_neighbor(self, neighbor_node):
        if neighbor_node not in self.neighbors:
            self.neighbors.append(neighbor_node)

    def read(self, address):
        return self.processor.execute_read(
            address=address,
            cache_controller=self.cache_controller
        )

    def write(self, address, data):
        self.processor.execute_write(
            address=address,
            data=data,
            cache_controller=self.cache_controller
        )

    def __repr__(self):
        neighbor_ids = [node.node_id for node in self.neighbors]

        return (
            f"Node(id={self.node_id}, "
            f"neighbors={neighbor_ids}, "
            f"processor={self.processor}, "
            f"cache={self.cache})"
        )