from message import Message
from cycle_logger import CycleLogger
from cache_state import CacheState
from stats_collector import StatsCollector


class ClockedSimulator:

    def __init__(self, network, enable_speculation=True):
        self.network = network
        self.enable_speculation = enable_speculation
        self.cycle = 0
        self.messages_in_flight = []
        self.logger = CycleLogger()
        self.logger.start_cycle(0)

        self.next_transaction_id = 0
        self.stats = StatsCollector()

    def allocate_transaction_id(self):
        transaction_id = self.next_transaction_id
        self.next_transaction_id += 1
        return transaction_id


    def create_message(
        self,
        message_type,
        source,
        destination,
        address=None,
        data=None,
        version=None,
        transaction_id=None,
        source_holder=None,
        requester=None
    ):
        path, distance = self.network.shortest_path(source, destination)

        message = Message(
            message_type=message_type,
            source=source,
            destination=destination,
            path=path,
            address=address,
            data=data,
            version=version,
            transaction_id=transaction_id,
            source_holder=source_holder,
            requester=requester
        )

        self.messages_in_flight.append(message)

        self.stats.record_message_created(
            cycle=self.cycle,
            message_type=message_type,
            source=source,
            destination=destination,
            address=address,
            path_distance=distance,
            transaction_id=transaction_id
        )

        self.logger.log_network(
            self.cycle,
            f"Created {message_type} from {source} to {destination} "
            f"for address {address}, path={path}, distance={distance}, "
            f"transaction_id={transaction_id}"
        )

        return message


    def execute_instruction(self, instruction):
        opcode = instruction.opcode
        processor_id = instruction.processor_id
        args = instruction.args

        if opcode == "READ":
            if len(args) != 1:
                raise ValueError("READ format: cycle processor READ address")

            address = int(args[0])

            self.stats.record_read_issued(
                cycle=self.cycle,
                requester=processor_id,
                address=address
            )

            self.issue_processor_read(processor_id, address)

        elif opcode == "WRITE":
            if len(args) != 2:
                raise ValueError("WRITE format: cycle processor WRITE address data")

            address = int(args[0])
            data = args[1]

            self.stats.record_write_issued(
                cycle=self.cycle,
                requester=processor_id,
                address=address
            )

            self.issue_processor_write(processor_id, address, data)

        elif opcode == "DIRECT_READ":
            if len(args) != 2:
                raise ValueError(
                    "DIRECT_READ format: cycle processor DIRECT_READ address destination"
                )

            address = int(args[0])
            destination = args[1]

            self.issue_direct_read_request(
                processor_id=processor_id,
                address=address,
                destination_id=destination
            )

        elif opcode == "INVALIDATE":
            raise ValueError(
                "INVALIDATE is no longer a normal instruction. "
                "Use WRITE so the home directory generates real invalidations."
            )

        else:
            raise ValueError(f"Unknown opcode: {opcode}")


    def issue_processor_read(self, processor_id, address):
        node = self.network.nodes[processor_id]

        if node.cache.contains_valid_block(address):
            data = node.cache.read(address)
            line = node.cache.get_line(address)

            self.stats.record_local_hit(
                cycle=self.cycle,
                requester=processor_id,
                address=address
            )

            self.logger.log_processor(
                self.cycle,
                f"{processor_id} READ address {address}: local cache hit, "
                f"data={data}, version={line.version}"
            )
            return

        self.stats.record_local_miss(
            cycle=self.cycle,
            requester=processor_id,
            address=address
        )

        self.logger.log_processor(
            self.cycle,
            f"{processor_id} issued READ for address {address}"
        )

        self.logger.log_cache(
            self.cycle,
            f"{processor_id} local cache miss for address {address}"
        )

        local_switch_id = self.network.get_local_switch_for_processor(processor_id)

        self.create_message(
            message_type="READ_TO_LOCAL_SWITCH",
            source=processor_id,
            destination=local_switch_id,
            address=address,
            requester=processor_id
        )


    def issue_processor_write(self, processor_id, address, data):
        """
        Processor issues a normal WRITE.

        If the line is already MODIFIED/EXCLUSIVE locally, write immediately.
        Otherwise, request exclusive ownership from the home directory.
        """
        node = self.network.nodes[processor_id]
        line = node.cache.get_line(address)

        if (
            line is not None
            and line.is_valid()
            and line.state in (CacheState.MODIFIED, CacheState.EXCLUSIVE)
        ):
            new_version = line.version + 1

            node.cache.write(
                address=address,
                data=data,
                state=CacheState.MODIFIED,
                version=new_version
            )

            self.network.register_installed_cache_line(
                processor_id=processor_id,
                address=address,
                state=CacheState.MODIFIED,
                version=new_version
            )

            self.logger.log_processor(
                self.cycle,
                f"{processor_id} WRITE address {address}: local ownership hit, "
                f"wrote data={data}, version={new_version}"
            )
            return

        self.stats.record_exclusive_request(
            cycle=self.cycle,
            requester=processor_id,
            address=address
        )

        self.logger.log_processor(
            self.cycle,
            f"{processor_id} issued WRITE for address {address}, data={data}"
        )

        if line is None or not line.is_valid():
            self.logger.log_cache(
                self.cycle,
                f"{processor_id} write miss for address {address}; requesting ownership"
            )
        else:
            self.logger.log_cache(
                self.cycle,
                f"{processor_id} has address {address} in state={line.state.value}; "
                f"requesting upgrade to ownership"
            )

        local_switch_id = self.network.get_local_switch_for_processor(processor_id)
        home_switch_id = self.network.get_home_switch_for_address(address)

        self.create_message(
            message_type="EXCLUSIVE_REQUEST",
            source=local_switch_id,
            destination=home_switch_id,
            address=address,
            data=data,
            requester=processor_id
        )

    def issue_direct_read_request(self, processor_id, address, destination_id):
        self.create_message(
            message_type="READ_REQUEST",
            source=processor_id,
            destination=destination_id,
            address=address,
            requester=processor_id
        )

        self.logger.log_processor(
            self.cycle,
            f"{processor_id} issued DIRECT_READ request for address {address} "
            f"toward {destination_id}"
        )

    def find_speculative_candidate(self, requester, local_switch_id, address):
        """
        Local-only speculation rule.

        The local switch checks only its own child-leaf directory summary.
        It does not inspect express-neighbor switch directories.
        """
        return self.find_candidate_in_switch_directory(
            switch_id=local_switch_id,
            requester=requester,
            address=address
        )

    def find_candidate_in_switch_directory(self, switch_id, requester, address):
        switch = self.network.switches[switch_id]
        holders = switch.lookup_local_holders(address)

        for processor_id, metadata in holders.items():
            if processor_id == requester:
                continue

            state = metadata["state"]

            if state == CacheState.SHARED or getattr(state, "value", None) == "S":
                return processor_id

        return None

    def handle_read_at_local_switch(self, message):
        local_switch_id = message.destination
        requester = message.requester
        address = message.address

        # ------------------------------------------------------------
        # Baseline mode:
        # If speculation is disabled, skip the neighbor lookup entirely
        # and immediately fall back to the normal home-directory path.
        # ------------------------------------------------------------
        if not self.enable_speculation:
            self.logger.log_switch(
                self.cycle,
                f"{local_switch_id} speculation disabled for READ address "
                f"{address}; falling back to home"
            )

            self.issue_home_read_miss(
                source=local_switch_id,
                requester=requester,
                address=address
            )
            return

        # ------------------------------------------------------------
        # Optimized mode:
        # Try to find a local speculative candidate under the same switch.
        # ------------------------------------------------------------
        candidate_holder = self.find_speculative_candidate(
            requester=requester,
            local_switch_id=local_switch_id,
            address=address
        )

        # ------------------------------------------------------------
        # No local candidate found.
        # Use the normal home-directory read path.
        # ------------------------------------------------------------
        if candidate_holder is None:
            self.logger.log_switch(
                self.cycle,
                f"{local_switch_id} found no speculative candidate for READ "
                f"address {address}; falling back to home"
            )

            self.issue_home_read_miss(
                source=local_switch_id,
                requester=requester,
                address=address
            )
            return

        # ------------------------------------------------------------
        # Candidate found.
        # Double-check that the candidate cache still has a valid shared line.
        # The local switch summary can be stale, so this safety check matters.
        # ------------------------------------------------------------
        candidate_node = self.network.nodes[candidate_holder]
        candidate_line = candidate_node.cache.get_line(address)

        if (
                candidate_line is None
                or not candidate_line.is_valid()
                or candidate_line.state != CacheState.SHARED
        ):
            self.logger.log_switch(
                self.cycle,
                f"{local_switch_id} candidate {candidate_holder} for address "
                f"{address} was stale or not shared; falling back to home"
            )

            self.issue_home_read_miss(
                source=local_switch_id,
                requester=requester,
                address=address
            )
            return

        # ------------------------------------------------------------
        # Start speculative read transaction.
        # The neighbor provides fast speculative data.
        # The home directory validates correctness in parallel.
        # ------------------------------------------------------------
        transaction_id = self.allocate_transaction_id()

        self.stats.record_speculative_attempt(
            cycle=self.cycle,
            transaction_id=transaction_id,
            requester=requester,
            source_holder=candidate_holder,
            address=address
        )

        self.logger.log_switch(
            self.cycle,
            f"{local_switch_id} found speculative candidate {candidate_holder} "
            f"for READ address {address}; transaction_id={transaction_id}"
        )

        # Ask the neighboring shared cache to send speculative data.
        self.create_message(
            message_type="SPECULATIVE_FETCH",
            source=local_switch_id,
            destination=candidate_holder,
            address=address,
            transaction_id=transaction_id,
            requester=requester
        )

        # Ask the home directory to validate that speculative copy.
        home_switch_id = self.network.get_home_switch_for_address(address)

        self.create_message(
            message_type="VALIDATION_REQUEST",
            source=local_switch_id,
            destination=home_switch_id,
            address=address,
            version=candidate_line.version,
            transaction_id=transaction_id,
            source_holder=candidate_holder,
            requester=requester
        )

    def issue_home_read_miss(self, source, requester, address):
        home_switch_id = self.network.get_home_switch_for_address(address)

        self.create_message(
            message_type="READ_MISS",
            source=source,
            destination=home_switch_id,
            address=address,
            requester=requester
        )

    def step(self):
        self.logger.start_cycle(self.cycle)
        completed_messages = []

        # ------------------------------------------------------------
        # Move messages that are currently in flight.
        # Messages stop at switches and enter the switch queue.
        # ------------------------------------------------------------
        for message in list(self.messages_in_flight):
            if message.completed:
                completed_messages.append(message)
                continue

            if message.waiting_in_switch_queue:
                continue

            current_location = message.current_location()
            next_location = message.next_location()

            # This message is already at its final destination.
            # Do NOT record switch processing here because this message
            # did not come out of a switch queue in this branch.
            if next_location is None:
                completed_messages.append(message)
                continue

            # If the message is currently sitting at a switch, enqueue it.
            if current_location in self.network.switches:
                switch = self.network.switches[current_location]
                accepted = switch.enqueue_message(message)

                if accepted:
                    message.waiting_in_switch_queue = True

                    self.stats.record_switch_enqueue(
                        switch_id=current_location,
                        queue_depth=switch.queue_depth()
                    )

                    self.logger.log_switch(
                        self.cycle,
                        f"{current_location} enqueued {message.message_type} "
                        f"for address {message.address}; "
                        f"queue_depth={switch.queue_depth()}"
                    )
                else:
                    self.logger.log_switch(
                        self.cycle,
                        f"{current_location} DROPPED {message.message_type} "
                        f"for address {message.address}; queue full"
                    )
                    completed_messages.append(message)

                continue

            # Otherwise move the message one hop forward.
            old_location = current_location
            message.advance_one_hop()
            new_location = message.current_location()

            self.logger.log_network(
                self.cycle,
                f"{message.message_type} for address {message.address} moved "
                f"{old_location} -> {new_location}"
            )

            # If it arrived at a switch, enqueue it.
            if new_location in self.network.switches:
                switch = self.network.switches[new_location]
                accepted = switch.enqueue_message(message)

                if accepted:
                    message.waiting_in_switch_queue = True

                    self.stats.record_switch_enqueue(
                        switch_id=new_location,
                        queue_depth=switch.queue_depth()
                    )

                    self.logger.log_switch(
                        self.cycle,
                        f"{new_location} enqueued {message.message_type} "
                        f"for address {message.address}; "
                        f"queue_depth={switch.queue_depth()}"
                    )
                else:
                    self.logger.log_switch(
                        self.cycle,
                        f"{new_location} DROPPED {message.message_type} "
                        f"for address {message.address}; queue full"
                    )
                    completed_messages.append(message)

            elif message.completed:
                completed_messages.append(message)

        # ------------------------------------------------------------
        # Each switch processes at most one queued message per cycle.
        # This is where switch processing should be counted.
        # ------------------------------------------------------------
        for switch_id, switch in self.network.switches.items():
            if not switch.has_pending_message():
                continue

            message = switch.process_one_message()
            message.waiting_in_switch_queue = False

            old_location = message.current_location()
            next_location = message.next_location()

            # Count the queue-processing event immediately after the switch
            # removes the message from its queue.
            self.stats.record_switch_process(
                switch_id=switch_id,
                remaining_queue_depth=switch.queue_depth()
            )

            self.logger.log_switch(
                self.cycle,
                f"{switch_id} processed one message: "
                f"{message.message_type} for address {message.address}; "
                f"remaining_queue_depth={switch.queue_depth()}"
            )

            # If the message's destination is this switch, complete it here.
            if next_location is None:
                completed_messages.append(message)
                continue

            # Otherwise move it one hop out of the switch.
            message.advance_one_hop()
            new_location = message.current_location()

            self.logger.log_network(
                self.cycle,
                f"{message.message_type} for address {message.address} moved "
                f"{old_location} -> {new_location}"
            )

            # If the next hop is another switch, enqueue it there.
            if new_location in self.network.switches:
                next_switch = self.network.switches[new_location]
                accepted = next_switch.enqueue_message(message)

                if accepted:
                    message.waiting_in_switch_queue = True

                    self.stats.record_switch_enqueue(
                        switch_id=new_location,
                        queue_depth=next_switch.queue_depth()
                    )

                    self.logger.log_switch(
                        self.cycle,
                        f"{new_location} received and enqueued {message.message_type} "
                        f"for address {message.address}; "
                        f"queue_depth={next_switch.queue_depth()}"
                    )
                else:
                    self.logger.log_switch(
                        self.cycle,
                        f"{new_location} DROPPED {message.message_type} "
                        f"for address {message.address}; queue full"
                    )
                    completed_messages.append(message)

            elif message.completed:
                completed_messages.append(message)

        # ------------------------------------------------------------
        # Handle all messages that completed this cycle.
        # ------------------------------------------------------------
        for message in completed_messages:
            if message in self.messages_in_flight:
                self.stats.record_message_completed(
                    cycle=self.cycle,
                    message_type=message.message_type,
                    source=message.source,
                    destination=message.destination,
                    address=message.address,
                    transaction_id=message.transaction_id
                )

                self.handle_completed_message(message)
                self.messages_in_flight.remove(message)

        # ------------------------------------------------------------
        # Advance switch queues into the next cycle.
        # ------------------------------------------------------------
        for switch in self.network.switches.values():
            switch.advance_cycle()

        self.cycle += 1

    def handle_completed_message(self, message):
        destination = message.destination

        if destination in self.network.nodes:
            self.handle_processor_arrival(message)
        elif destination in self.network.switches:
            self.handle_switch_arrival(message)

    def handle_processor_arrival(self, message):
        destination = message.destination
        node = self.network.nodes[destination]

        if message.message_type == "READ_REQUEST":
            line = node.cache.get_line(message.address)

            if line is not None and line.is_valid():
                self.logger.log_cache(
                    self.cycle,
                    f"{destination} has address {message.address}: "
                    f"data={line.data}, state={line.state.value}, version={line.version}"
                )

                self.create_message(
                    message_type="READ_RESPONSE",
                    source=destination,
                    destination=message.source,
                    address=message.address,
                    data=line.data,
                    version=line.version,
                    requester=message.requester
                )
            else:
                self.logger.log_cache(
                    self.cycle,
                    f"{destination} does not have valid address {message.address}"
                )

        elif message.message_type in ("READ_RESPONSE", "AUTHORITATIVE_DATA"):
            self.handle_authoritative_data_arrival(
                processor_id=destination,
                address=message.address,
                data=message.data,
                version=message.version
            )

        elif message.message_type == "SPECULATIVE_FETCH":
            self.handle_speculative_fetch_at_processor(message)

        elif message.message_type == "SPECULATIVE_DATA":
            self.handle_speculative_data_at_processor(message)

        elif message.message_type == "VALIDATION_SUCCESS":
            self.handle_validation_success_at_processor(message)

        elif message.message_type == "VALIDATION_FAIL":
            self.handle_validation_fail_at_processor(message)

        elif message.message_type == "INVALIDATE":
            self.handle_invalidate_at_processor(message)

        elif message.message_type == "EXCLUSIVE_GRANT":
            self.handle_exclusive_grant_at_processor(message)

    def handle_speculative_fetch_at_processor(self, message):
        destination = message.destination
        node = self.network.nodes[destination]
        line = node.cache.get_line(message.address)

        if (
            line is not None
            and line.is_valid()
            and line.state == CacheState.SHARED
        ):
            self.logger.log_cache(
                self.cycle,
                f"{destination} accepted SPECULATIVE_FETCH for address "
                f"{message.address}: data={line.data}, version={line.version}"
            )

            self.create_message(
                message_type="SPECULATIVE_DATA",
                source=destination,
                destination=message.requester,
                address=message.address,
                data=line.data,
                version=line.version,
                transaction_id=message.transaction_id,
                source_holder=destination,
                requester=message.requester
            )
        else:
            self.logger.log_cache(
                self.cycle,
                f"{destination} rejected SPECULATIVE_FETCH for address "
                f"{message.address}: no valid shared copy"
            )


    def handle_speculative_data_at_processor(self, message):
        destination = message.destination
        node = self.network.nodes[destination]

        self.stats.record_speculative_data_received(
            cycle=self.cycle,
            transaction_id=message.transaction_id
        )

        self.logger.log_processor(
            self.cycle,
            f"{destination} received SPECULATIVE_DATA for address "
            f"{message.address} from {message.source_holder}: "
            f"data={message.data}, version={message.version}, "
            f"transaction_id={message.transaction_id}"
        )

        speculative_load, status = node.processor.begin_speculative_load(
            transaction_id=message.transaction_id,
            address=message.address,
            data=message.data,
            version=message.version,
            source_holder=message.source_holder
        )

        if status == "PENDING":
            self.logger.log_processor(
                self.cycle,
                f"{destination} stored transaction_id={message.transaction_id} "
                f"in speculative load buffer"
            )

        elif status == "VALIDATED_IMMEDIATELY":
            self.logger.log_processor(
                self.cycle,
                f"{destination} immediately validated speculative load "
                f"transaction_id={message.transaction_id}, "
                f"address={message.address}, data={message.data}"
            )

            self.install_validated_speculative_line(
                processor_id=destination,
                address=message.address,
                data=message.data,
                version=message.version,
                transaction_id=message.transaction_id
            )

        elif status == "SQUASHED_IMMEDIATELY":
            self.stats.record_speculative_squash(
                cycle=self.cycle,
                transaction_id=message.transaction_id
            )

            self.logger.log_processor(
                self.cycle,
                f"{destination} discarded SPECULATIVE_DATA for transaction_id="
                f"{message.transaction_id} because validation already failed"
            )


    def handle_validation_success_at_processor(self, message):
        destination = message.destination
        node = self.network.nodes[destination]

        speculative_load = node.processor.validate_speculative_load(
            message.transaction_id
        )

        if speculative_load is None:
            self.logger.log_processor(
                self.cycle,
                f"{destination} received VALIDATION_SUCCESS for transaction_id="
                f"{message.transaction_id} before speculative data arrived"
            )
        else:
            self.logger.log_processor(
                self.cycle,
                f"{destination} VALIDATED speculative load "
                f"transaction_id={message.transaction_id}, "
                f"address={speculative_load.address}, "
                f"data={speculative_load.data}"
            )

            self.install_validated_speculative_line(
                processor_id=destination,
                address=speculative_load.address,
                data=speculative_load.data,
                version=speculative_load.version,
                transaction_id=message.transaction_id
            )


    def handle_validation_fail_at_processor(self, message):
        destination = message.destination
        node = self.network.nodes[destination]

        speculative_load = node.processor.squash_speculative_load(
            message.transaction_id
        )

        self.stats.record_speculative_squash(
            cycle=self.cycle,
            transaction_id=message.transaction_id
        )

        if speculative_load is None:
            self.logger.log_processor(
                self.cycle,
                f"{destination} received VALIDATION_FAIL for transaction_id="
                f"{message.transaction_id} before speculative data arrived"
            )
        else:
            self.logger.log_processor(
                self.cycle,
                f"{destination} SQUASHED speculative load "
                f"transaction_id={message.transaction_id}, "
                f"address={speculative_load.address}"
            )


    def handle_invalidate_at_processor(self, message):
        destination = message.destination
        node = self.network.nodes[destination]

        did_invalidate = node.cache.invalidate(message.address)

        if did_invalidate:
            self.network.unregister_cache_line(destination, message.address)

            self.logger.log_cache(
                self.cycle,
                f"{destination} invalidated cache line for address {message.address}"
            )
        else:
            self.logger.log_cache(
                self.cycle,
                f"{destination} received INVALIDATE for address {message.address}, "
                f"but no valid cache line was present"
            )

        squashed = node.processor.handle_invalidation_for_address(message.address)

        if message.address in node.processor.validated_operands:
            self.logger.log_processor(
                self.cycle,
                f"{destination} kept validated operand for address "
                f"{message.address} after invalidating cache line"
            )

        for speculative_load in squashed:
            self.stats.record_speculative_squash(
                cycle=self.cycle,
                transaction_id=speculative_load.transaction_id
            )

            self.logger.log_processor(
                self.cycle,
                f"{destination} squashed pending speculative load "
                f"transaction_id={speculative_load.transaction_id}, "
                f"address={speculative_load.address} due to invalidation"
            )

        home_switch_id = self.network.get_home_switch_for_address(message.address)

        self.create_message(
            message_type="INVALIDATE_ACK",
            source=destination,
            destination=home_switch_id,
            address=message.address,
            requester=destination
        )

    def handle_exclusive_grant_at_processor(self, message):
        destination = message.destination
        node = self.network.nodes[destination]

        node.cache.write(
            address=message.address,
            data=message.data,
            state=CacheState.MODIFIED,
            version=message.version
        )

        self.network.register_installed_cache_line(
            processor_id=destination,
            address=message.address,
            state=CacheState.MODIFIED,
            version=message.version
        )

        self.logger.log_processor(
            self.cycle,
            f"{destination} received EXCLUSIVE_GRANT for address {message.address}; "
            f"wrote data={message.data}, state=M, version={message.version}"
        )

        self.logger.log_cache(
            self.cycle,
            f"{destination} installed MODIFIED address {message.address}: "
            f"data={message.data}, version={message.version}"
        )


    def handle_authoritative_data_arrival(self, processor_id, address, data, version):
        node = self.network.nodes[processor_id]

        self.stats.record_authoritative_data_installed(
            cycle=self.cycle,
            requester=processor_id,
            address=address
        )

        self.logger.log_processor(
            self.cycle,
            f"{processor_id} received AUTHORITATIVE_DATA for address {address}: "
            f"data={data}, version={version}"
        )

        node.cache.write(
            address=address,
            data=data,
            state=CacheState.SHARED,
            version=version
        )

        self.network.register_installed_cache_line(
            processor_id=processor_id,
            address=address,
            state=CacheState.SHARED,
            version=version
        )

        self.logger.log_cache(
            self.cycle,
            f"{processor_id} installed authoritative address {address}: "
            f"data={data}, state=S, version={version}"
        )


    def install_validated_speculative_line(
        self,
        processor_id,
        address,
        data,
        version,
        transaction_id=None
    ):
        node = self.network.nodes[processor_id]

        if transaction_id is not None:
            self.stats.record_validated_speculative_data_installed(
                cycle=self.cycle,
                requester=processor_id,
                address=address,
                transaction_id=transaction_id
            )

        node.cache.write(
            address=address,
            data=data,
            state=CacheState.SHARED,
            version=version
        )

        self.network.register_installed_cache_line(
            processor_id=processor_id,
            address=address,
            state=CacheState.SHARED,
            version=version
        )

        self.logger.log_cache(
            self.cycle,
            f"{processor_id} installed validated speculative address "
            f"{address}: data={data}, state=S, version={version}"
        )

    def handle_switch_arrival(self, message):
        if message.message_type == "READ_TO_LOCAL_SWITCH":
            self.handle_read_at_local_switch(message)

        elif message.message_type == "READ_MISS":
            self.handle_read_miss_at_home(message)

        elif message.message_type == "VALIDATION_REQUEST":
            self.handle_validation_request_at_home(message)

        elif message.message_type == "EXCLUSIVE_REQUEST":
            self.handle_exclusive_request_at_home(message)

        elif message.message_type == "INVALIDATE_ACK":
            self.handle_invalidate_ack_at_home(message)


    def handle_validation_request_at_home(self, message):
        switch = self.network.switches[message.destination]

        valid = switch.validate_speculative_copy(
            address=message.address,
            requester=message.requester,
            source_holder=message.source_holder,
            version=message.version
        )

        if valid:
            self.stats.record_validation_success(
                cycle=self.cycle,
                transaction_id=message.transaction_id
            )

            self.logger.log_directory(
                self.cycle,
                f"{message.destination} VALIDATED address {message.address} "
                f"for requester={message.requester}, "
                f"source_holder={message.source_holder}, "
                f"version={message.version}"
            )

            self.create_message(
                message_type="VALIDATION_SUCCESS",
                source=message.destination,
                destination=message.requester,
                address=message.address,
                version=message.version,
                transaction_id=message.transaction_id,
                source_holder=message.source_holder,
                requester=message.requester
            )
        else:
            self.stats.record_validation_failure(
                cycle=self.cycle,
                transaction_id=message.transaction_id
            )

            self.logger.log_directory(
                self.cycle,
                f"{message.destination} REJECTED validation for address "
                f"{message.address}, requester={message.requester}, "
                f"source_holder={message.source_holder}, version={message.version}"
            )

            self.create_message(
                message_type="VALIDATION_FAIL",
                source=message.destination,
                destination=message.requester,
                address=message.address,
                version=message.version,
                transaction_id=message.transaction_id,
                source_holder=message.source_holder,
                requester=message.requester
            )

    def handle_read_miss_at_home(self, message):
        home_switch = self.network.switches[message.destination]
        entry = home_switch.get_or_create_directory_entry(message.address)

        if not entry.sharers:
            self.logger.log_directory(
                self.cycle,
                f"{message.destination} READ_MISS for address {message.address} "
                f"has no sharers; memory fallback not implemented"
            )
            return

        holder = sorted(entry.sharers)[0]
        holder_node = self.network.nodes[holder]
        line = holder_node.cache.get_line(message.address)

        if line is None or not line.is_valid():
            self.logger.log_directory(
                self.cycle,
                f"{message.destination} READ_MISS found stale holder {holder} "
                f"for address {message.address}; unable to supply data"
            )
            return

        entry.sharers.add(message.requester)

        self.logger.log_directory(
            self.cycle,
            f"{message.destination} served READ_MISS for address {message.address} "
            f"using holder={holder}; requester={message.requester} added as sharer"
        )

        self.create_message(
            message_type="AUTHORITATIVE_DATA",
            source=message.destination,
            destination=message.requester,
            address=message.address,
            data=line.data,
            version=line.version,
            requester=message.requester
        )


    def handle_exclusive_request_at_home(self, message):
        home_switch = self.network.switches[message.destination]
        entry = home_switch.get_or_create_directory_entry(message.address)

        if entry.invalidation_pending:
            self.logger.log_directory(
                self.cycle,
                f"{message.destination} cannot process EXCLUSIVE_REQUEST for "
                f"address {message.address}; invalidation already pending"
            )
            return

        invalidation_targets = entry.begin_exclusive_request(
            requester=message.requester,
            write_data=message.data
        )

        self.logger.log_directory(
            self.cycle,
            f"{message.destination} began EXCLUSIVE_REQUEST for address "
            f"{message.address}, requester={message.requester}, "
            f"targets={sorted(invalidation_targets)}"
        )

        for target in sorted(invalidation_targets):
            self.stats.record_invalidation_sent(
                cycle=self.cycle,
                target=target,
                address=message.address
            )

            self.create_message(
                message_type="INVALIDATE",
                source=message.destination,
                destination=target,
                address=message.address,
                requester=message.requester
            )

        if not invalidation_targets:
            self.finish_exclusive_transaction(
                home_switch_id=message.destination,
                address=message.address
            )


    def handle_invalidate_ack_at_home(self, message):
        home_switch = self.network.switches[message.destination]
        entry = home_switch.get_or_create_directory_entry(message.address)

        entry.receive_invalidation_ack(message.requester)

        self.stats.record_invalidation_ack(
            cycle=self.cycle,
            source=message.requester,
            address=message.address
        )

        self.logger.log_directory(
            self.cycle,
            f"{message.destination} received INVALIDATE_ACK for address "
            f"{message.address} from {message.requester}; "
            f"remaining_acks={sorted(entry.pending_invalidation_acks)}"
        )

        if entry.invalidations_complete():
            self.finish_exclusive_transaction(
                home_switch_id=message.destination,
                address=message.address
            )


    def finish_exclusive_transaction(self, home_switch_id, address):
        home_switch = self.network.switches[home_switch_id]
        entry = home_switch.get_or_create_directory_entry(address)

        writer, data, version = entry.complete_exclusive_grant()

        self.stats.record_exclusive_grant(
            cycle=self.cycle,
            requester=writer,
            address=address
        )

        self.logger.log_directory(
            self.cycle,
            f"{home_switch_id} completed exclusive ownership for address "
            f"{address}; owner={writer}, version={version}"
        )

        self.create_message(
            message_type="EXCLUSIVE_GRANT",
            source=home_switch_id,
            destination=writer,
            address=address,
            data=data,
            version=version,
            requester=writer
        )

    def run(self, num_cycles):
        for _ in range(num_cycles):
            self.step()

    def print_log(self):
        self.logger.print_all_cycles()

    def print_stats_report(self):
        self.stats.print_report()

    def print_switch_stats(self):
        print("Switch statistics:")
        for switch_id, switch in self.network.switches.items():
            print(f"  {switch_id}: {switch.stats}")