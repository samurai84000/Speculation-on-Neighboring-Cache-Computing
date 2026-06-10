from collections import deque
from directory_entry import DirectoryEntry


class Switch:
    def __init__(self, switch_id, queue_capacity=None):
        self.switch_id = switch_id

        # Messages available to process this cycle.
        self.current_queue = deque()

        # Messages that arrived this cycle.
        # They become processable next cycle.
        self.next_queue = deque()

        self.queue_capacity = queue_capacity

        # Local cache summary:
        # address -> processor_id -> metadata
        self.local_directory = {}

        # Authoritative home directory entries for blocks mapped here.
        self.home_directory = {}

        self.stats = {
            "messages_enqueued": 0,
            "messages_processed": 0,
            "messages_dropped": 0,
            "max_queue_depth": 0,
        }

    def total_queue_depth(self):
        return len(self.current_queue) + len(self.next_queue)

    def can_accept_message(self):
        if self.queue_capacity is None:
            return True

        return self.total_queue_depth() < self.queue_capacity

    def enqueue_message(self, message):
        if not self.can_accept_message():
            self.stats["messages_dropped"] += 1
            return False

        self.next_queue.append(message)
        self.stats["messages_enqueued"] += 1
        self.stats["max_queue_depth"] = max(
            self.stats["max_queue_depth"],
            self.total_queue_depth()
        )

        return True

    def has_pending_message(self):
        return len(self.current_queue) > 0

    def process_one_message(self):
        if not self.current_queue:
            return None

        self.stats["messages_processed"] += 1
        return self.current_queue.popleft()

    def advance_cycle(self):
        while self.next_queue:
            self.current_queue.append(self.next_queue.popleft())

    def queue_depth(self):
        return self.total_queue_depth()

    def register_cache_line(self, processor_id, address, state, version):
        if address not in self.local_directory:
            self.local_directory[address] = {}

        self.local_directory[address][processor_id] = {
            "state": state,
            "version": version
        }

    def unregister_cache_line(self, processor_id, address):
        if address not in self.local_directory:
            return

        if processor_id in self.local_directory[address]:
            del self.local_directory[address][processor_id]

        if not self.local_directory[address]:
            del self.local_directory[address]

    def lookup_local_holders(self, address):
        return self.local_directory.get(address, {})

    def get_or_create_directory_entry(self, address):
        if address not in self.home_directory:
            self.home_directory[address] = DirectoryEntry(address)

        return self.home_directory[address]

    def register_home_sharer(self, address, processor_id, version=0):
        entry = self.get_or_create_directory_entry(address)
        entry.sharers.add(processor_id)
        entry.version = version
        entry.state = "SHARED"

    def validate_speculative_copy(
        self,
        address,
        requester,
        source_holder,
        version
    ):
        entry = self.get_or_create_directory_entry(address)

        return entry.validate_speculative_copy(
            requester=requester,
            source_holder=source_holder,
            version=version
        )

    def __repr__(self):
        return (
            f"Switch(id={self.switch_id}, "
            f"current_queue={len(self.current_queue)}, "
            f"next_queue={len(self.next_queue)}, "
            f"stats={self.stats})"
        )