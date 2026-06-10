class SpeculativeLoad:
    def __init__(self, transaction_id, address, data, version, source_holder):
        self.transaction_id = transaction_id
        self.address = address
        self.data = data
        self.version = version
        self.source_holder = source_holder

        self.state = "PENDING_VALIDATION"

    def mark_validated(self):
        self.state = "VALIDATED"

    def squash(self):
        self.state = "SQUASHED"

    def commit(self):
        self.state = "COMMITTED"

    def is_pending(self):
        return self.state == "PENDING_VALIDATION"

    def is_validated(self):
        return self.state == "VALIDATED"

    def __repr__(self):
        return (
            f"SpeculativeLoad(transaction_id={self.transaction_id}, "
            f"address={self.address}, data={self.data}, "
            f"version={self.version}, source_holder={self.source_holder}, "
            f"state={self.state})"
        )