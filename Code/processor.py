from speculative_load import SpeculativeLoad


class Processor:
    def __init__(self, processor_id):
        self.processor_id = processor_id
        self.registers = {}

        # transaction_id -> SpeculativeLoad
        self.speculative_loads = {}

        # address -> stable loaded value
        # Once a speculative load validates, its value goes here.
        self.validated_operands = {}

        # Handles out-of-order arrival:
        # validation can arrive before SPECULATIVE_DATA.
        self.pending_validation_results = {}

        self.waiting_for_validation = False

    def execute_read(self, address, cache_controller):
        return cache_controller.read_request(address)

    def execute_write(self, address, data, cache_controller):
        cache_controller.write_request(address, data)

    def begin_speculative_load(
        self,
        transaction_id,
        address,
        data,
        version,
        source_holder
    ):
        speculative_load = SpeculativeLoad(
            transaction_id=transaction_id,
            address=address,
            data=data,
            version=version,
            source_holder=source_holder
        )

        pending_result = self.pending_validation_results.pop(transaction_id, None)

        if pending_result == "SUCCESS":
            speculative_load.mark_validated()
            self.validated_operands[address] = data
            return speculative_load, "VALIDATED_IMMEDIATELY"

        if pending_result == "FAIL":
            speculative_load.squash()
            return speculative_load, "SQUASHED_IMMEDIATELY"

        self.speculative_loads[transaction_id] = speculative_load
        self.waiting_for_validation = True
        return speculative_load, "PENDING"

    def validate_speculative_load(self, transaction_id):
        if transaction_id not in self.speculative_loads:
            self.pending_validation_results[transaction_id] = "SUCCESS"
            return None

        speculative_load = self.speculative_loads[transaction_id]
        speculative_load.mark_validated()

        self.validated_operands[speculative_load.address] = speculative_load.data

        del self.speculative_loads[transaction_id]

        if not self.speculative_loads:
            self.waiting_for_validation = False

        return speculative_load

    def squash_speculative_load(self, transaction_id):
        if transaction_id not in self.speculative_loads:
            self.pending_validation_results[transaction_id] = "FAIL"
            return None

        speculative_load = self.speculative_loads[transaction_id]
        speculative_load.squash()

        del self.speculative_loads[transaction_id]

        if not self.speculative_loads:
            self.waiting_for_validation = False

        return speculative_load

    def handle_invalidation_for_address(self, address):
        """
        Pending speculative loads are squashed.

        Validated operands are NOT destroyed.
        This models the rule:
            invalidation kills future cache use,
            not already-validated loaded values.
        """
        squashed = []

        for transaction_id, speculative_load in list(self.speculative_loads.items()):
            if speculative_load.address == address:
                speculative_load.squash()
                squashed.append(speculative_load)
                del self.speculative_loads[transaction_id]

        if not self.speculative_loads:
            self.waiting_for_validation = False

        return squashed

    def __repr__(self):
        return (
            f"Processor(id={self.processor_id}, "
            f"waiting_for_validation={self.waiting_for_validation}, "
            f"speculative_loads={self.speculative_loads}, "
            f"validated_operands={self.validated_operands})"
        )