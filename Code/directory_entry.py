class DirectoryEntry:
    def __init__(self, address):
        self.address = address

        self.state = "SHARED"
        self.version = 0
        self.sharers = set()
        self.owner = None

        self.invalidation_pending = False
        self.pending_invalidation_acks = set()
        self.pending_writer = None
        self.pending_write_data = None

    def can_validate_speculative_copy(self, requester, source_holder, version):
        if self.invalidation_pending:
            return False

        if self.version != version:
            return False

        if source_holder not in self.sharers:
            return False

        if self.state != "SHARED":
            return False

        return True

    def validate_speculative_copy(self, requester, source_holder, version):
        if not self.can_validate_speculative_copy(
            requester=requester,
            source_holder=source_holder,
            version=version
        ):
            return False

        # Once validation succeeds, requester becomes an official sharer.
        self.sharers.add(requester)
        return True

    def begin_exclusive_request(self, requester, write_data):
        """
        Starts an ownership transaction.

        Returns:
            set of processors that must be invalidated.
        """
        self.invalidation_pending = True
        self.pending_writer = requester
        self.pending_write_data = write_data

        targets = set(self.sharers)

        # If requester already has a shared copy, it does not need to invalidate itself.
        if requester in targets:
            targets.remove(requester)

        self.pending_invalidation_acks = set(targets)
        return targets

    def receive_invalidation_ack(self, processor_id):
        if processor_id in self.pending_invalidation_acks:
            self.pending_invalidation_acks.remove(processor_id)

    def invalidations_complete(self):
        return self.invalidation_pending and not self.pending_invalidation_acks

    def complete_exclusive_grant(self):
        """
        Finishes the write transaction and updates authoritative directory state.
        """
        writer = self.pending_writer
        data = self.pending_write_data

        self.sharers.clear()
        self.owner = writer
        self.state = "MODIFIED"
        self.version += 1

        self.invalidation_pending = False
        self.pending_writer = None
        self.pending_write_data = None

        return writer, data, self.version

    def __repr__(self):
        return (
            f"DirectoryEntry(address={self.address}, "
            f"state={self.state}, version={self.version}, "
            f"sharers={self.sharers}, owner={self.owner}, "
            f"invalidation_pending={self.invalidation_pending}, "
            f"pending_acks={self.pending_invalidation_acks}, "
            f"pending_writer={self.pending_writer})"
        )