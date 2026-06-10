class Message:
    def __init__(
        self,
        message_type,
        source,
        destination,
        path,
        address=None,
        data=None,
        version=None,
        transaction_id=None,
        source_holder=None,
        requester=None
    ):
        self.message_type = message_type
        self.source = source
        self.destination = destination
        self.path = path

        self.address = address
        self.data = data
        self.version = version

        self.transaction_id = transaction_id
        self.source_holder = source_holder
        self.requester = requester

        self.current_hop_index = 0
        self.completed = False
        self.waiting_in_switch_queue = False

    def current_location(self):
        return self.path[self.current_hop_index]

    def next_location(self):
        if self.current_hop_index + 1 < len(self.path):
            return self.path[self.current_hop_index + 1]
        return None

    def advance_one_hop(self):
        if self.completed:
            return

        if self.current_hop_index + 1 < len(self.path):
            self.current_hop_index += 1

        if self.current_hop_index == len(self.path) - 1:
            self.completed = True

    def __repr__(self):
        return (
            f"Message(type={self.message_type}, "
            f"source={self.source}, destination={self.destination}, "
            f"address={self.address}, transaction_id={self.transaction_id}, "
            f"current={self.current_location()}, path={self.path})"
        )