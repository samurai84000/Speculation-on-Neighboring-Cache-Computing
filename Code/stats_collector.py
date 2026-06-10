# stats_collector.py

from dataclasses import dataclass, field
from typing import Dict, Optional, List


@dataclass
class ReadRecord:
    requester: str
    address: int
    start_cycle: int
    completed_cycle: Optional[int] = None
    completed_by: Optional[str] = None  # "local_hit", "authoritative", "speculative"
    transaction_id: Optional[int] = None


@dataclass
class SpeculationRecord:
    transaction_id: int
    requester: str
    source_holder: str
    address: int
    start_cycle: int
    validation_cycle: Optional[int] = None
    data_cycle: Optional[int] = None
    completed_cycle: Optional[int] = None
    result: Optional[str] = None  # "success", "fail", "squashed"


@dataclass
class MessageRecord:
    message_type: str
    source: str
    destination: str
    address: Optional[int]
    created_cycle: int
    path_distance: int
    transaction_id: Optional[int] = None
    completed_cycle: Optional[int] = None


class StatsCollector:
    def __init__(self):
        self.total_reads = 0
        self.total_writes = 0

        self.local_cache_hits = 0
        self.local_cache_misses = 0

        self.authoritative_reads_completed = 0
        self.speculative_reads_completed = 0

        self.speculative_attempts = 0
        self.speculative_successes = 0
        self.speculative_failures = 0
        self.speculative_squashes = 0

        self.validation_successes = 0
        self.validation_failures = 0

        self.invalidations_sent = 0
        self.invalidations_acknowledged = 0
        self.exclusive_requests = 0
        self.exclusive_grants = 0

        self.messages_created = 0
        self.messages_completed = 0
        self.total_path_distance = 0

        self.switch_enqueues: Dict[str, int] = {}
        self.switch_processes: Dict[str, int] = {}
        self.switch_max_queue_depth: Dict[str, int] = {}

        self.read_records: List[ReadRecord] = []
        self.open_reads: Dict[tuple, ReadRecord] = {}

        self.speculation_records: Dict[int, SpeculationRecord] = {}
        self.message_records: List[MessageRecord] = []

    # ----------------------------
    # Instruction-level events
    # ----------------------------

    def record_read_issued(self, cycle: int, requester: str, address: int):
        self.total_reads += 1

        record = ReadRecord(
            requester=requester,
            address=address,
            start_cycle=cycle,
        )

        key = (requester, address)
        self.open_reads[key] = record
        self.read_records.append(record)

    def record_write_issued(self, cycle: int, requester: str, address: int):
        self.total_writes += 1

    # ----------------------------
    # Cache events
    # ----------------------------

    def record_local_hit(self, cycle: int, requester: str, address: int):
        self.local_cache_hits += 1
        self._complete_read(
            cycle=cycle,
            requester=requester,
            address=address,
            completed_by="local_hit",
        )

    def record_local_miss(self, cycle: int, requester: str, address: int):
        self.local_cache_misses += 1

    def record_authoritative_data_installed(self, cycle: int, requester: str, address: int):
        self.authoritative_reads_completed += 1
        self._complete_read(
            cycle=cycle,
            requester=requester,
            address=address,
            completed_by="authoritative",
        )

    def record_validated_speculative_data_installed(
        self,
        cycle: int,
        requester: str,
        address: int,
        transaction_id: int,
    ):
        self.speculative_reads_completed += 1

        if transaction_id in self.speculation_records:
            spec = self.speculation_records[transaction_id]
            spec.completed_cycle = cycle
            if spec.result is None:
                spec.result = "success"

        self._complete_read(
            cycle=cycle,
            requester=requester,
            address=address,
            completed_by="speculative",
            transaction_id=transaction_id,
        )

    # ----------------------------
    # Speculation events
    # ----------------------------

    def record_speculative_attempt(
        self,
        cycle: int,
        transaction_id: int,
        requester: str,
        source_holder: str,
        address: int,
    ):
        self.speculative_attempts += 1

        self.speculation_records[transaction_id] = SpeculationRecord(
            transaction_id=transaction_id,
            requester=requester,
            source_holder=source_holder,
            address=address,
            start_cycle=cycle,
        )

    def record_validation_success(self, cycle: int, transaction_id: int):
        self.validation_successes += 1
        self.speculative_successes += 1

        if transaction_id in self.speculation_records:
            spec = self.speculation_records[transaction_id]
            spec.validation_cycle = cycle
            spec.result = "success"

    def record_validation_failure(self, cycle: int, transaction_id: int):
        self.validation_failures += 1
        self.speculative_failures += 1

        if transaction_id in self.speculation_records:
            spec = self.speculation_records[transaction_id]
            spec.validation_cycle = cycle
            spec.completed_cycle = cycle
            spec.result = "fail"

    def record_speculative_data_received(self, cycle: int, transaction_id: int):
        if transaction_id in self.speculation_records:
            self.speculation_records[transaction_id].data_cycle = cycle

    def record_speculative_squash(self, cycle: int, transaction_id: int):
        self.speculative_squashes += 1

        if transaction_id in self.speculation_records:
            spec = self.speculation_records[transaction_id]
            spec.completed_cycle = cycle
            spec.result = "squashed"

    # ----------------------------
    # Coherence write/invalidation events
    # ----------------------------

    def record_exclusive_request(self, cycle: int, requester: str, address: int):
        self.exclusive_requests += 1

    def record_exclusive_grant(self, cycle: int, requester: str, address: int):
        self.exclusive_grants += 1

    def record_invalidation_sent(self, cycle: int, target: str, address: int):
        self.invalidations_sent += 1

    def record_invalidation_ack(self, cycle: int, source: str, address: int):
        self.invalidations_acknowledged += 1

    # ----------------------------
    # Network / switch events
    # ----------------------------

    def record_message_created(
        self,
        cycle: int,
        message_type: str,
        source: str,
        destination: str,
        address: Optional[int],
        path_distance: int,
        transaction_id: Optional[int] = None,
    ):
        self.messages_created += 1
        self.total_path_distance += path_distance

        self.message_records.append(
            MessageRecord(
                message_type=message_type,
                source=source,
                destination=destination,
                address=address,
                created_cycle=cycle,
                path_distance=path_distance,
                transaction_id=transaction_id,
            )
        )

    def record_message_completed(
        self,
        cycle: int,
        message_type: str,
        source: str,
        destination: str,
        address: Optional[int],
        transaction_id: Optional[int] = None,
    ):
        self.messages_completed += 1

        for record in reversed(self.message_records):
            if (
                record.completed_cycle is None
                and record.message_type == message_type
                and record.source == source
                and record.destination == destination
                and record.address == address
                and record.transaction_id == transaction_id
            ):
                record.completed_cycle = cycle
                return

    def record_switch_enqueue(self, switch_id: str, queue_depth: int):
        self.switch_enqueues[switch_id] = self.switch_enqueues.get(switch_id, 0) + 1

        current_max = self.switch_max_queue_depth.get(switch_id, 0)
        self.switch_max_queue_depth[switch_id] = max(current_max, queue_depth)

    def record_switch_process(self, switch_id: str, remaining_queue_depth: int):
        self.switch_processes[switch_id] = self.switch_processes.get(switch_id, 0) + 1

        current_max = self.switch_max_queue_depth.get(switch_id, 0)
        self.switch_max_queue_depth[switch_id] = max(current_max, remaining_queue_depth)

    # ----------------------------
    # Internal helpers
    # ----------------------------

    def _complete_read(
        self,
        cycle: int,
        requester: str,
        address: int,
        completed_by: str,
        transaction_id: Optional[int] = None,
    ):
        key = (requester, address)

        if key not in self.open_reads:
            return

        record = self.open_reads.pop(key)
        record.completed_cycle = cycle
        record.completed_by = completed_by
        record.transaction_id = transaction_id

    def _latencies_for(self, completed_by: Optional[str] = None):
        values = []

        for record in self.read_records:
            if record.completed_cycle is None:
                continue

            if completed_by is not None and record.completed_by != completed_by:
                continue

            values.append(record.completed_cycle - record.start_cycle)

        return values

    @staticmethod
    def _average(values):
        if not values:
            return 0.0
        return sum(values) / len(values)

    def _speculative_data_arrival_latencies(self):
        values = []

        for spec in self.speculation_records.values():
            if spec.data_cycle is not None:
                values.append(spec.data_cycle - spec.start_cycle)

        return values

    def _speculative_head_start_latencies(self):
        values = []

        for spec in self.speculation_records.values():
            if spec.data_cycle is not None and spec.validation_cycle is not None:
                values.append(spec.validation_cycle - spec.data_cycle)

        return values

    # ----------------------------
    # Reporting
    # ----------------------------

    def summary_dict(self):
        all_read_latencies = self._latencies_for()
        authoritative_latencies = self._latencies_for("authoritative")
        speculative_latencies = self._latencies_for("speculative")
        local_hit_latencies = self._latencies_for("local_hit")
        spec_data_latencies = self._speculative_data_arrival_latencies()
        spec_head_start_latencies = self._speculative_head_start_latencies()

        speculative_success_rate = 0.0
        if self.speculative_attempts > 0:
            speculative_success_rate = self.speculative_successes / self.speculative_attempts

        average_path_distance = 0.0
        if self.messages_created > 0:
            average_path_distance = self.total_path_distance / self.messages_created

        return {
            "total_reads": self.total_reads,
            "total_writes": self.total_writes,

            "local_cache_hits": self.local_cache_hits,
            "local_cache_misses": self.local_cache_misses,

            "authoritative_reads_completed": self.authoritative_reads_completed,
            "speculative_reads_completed": self.speculative_reads_completed,

            "speculative_attempts": self.speculative_attempts,
            "speculative_successes": self.speculative_successes,
            "speculative_failures": self.speculative_failures,
            "speculative_squashes": self.speculative_squashes,
            "speculative_success_rate": speculative_success_rate,

            "validation_successes": self.validation_successes,
            "validation_failures": self.validation_failures,

            "exclusive_requests": self.exclusive_requests,
            "exclusive_grants": self.exclusive_grants,
            "invalidations_sent": self.invalidations_sent,
            "invalidations_acknowledged": self.invalidations_acknowledged,

            "messages_created": self.messages_created,
            "messages_completed": self.messages_completed,
            "average_path_distance": average_path_distance,

            "average_read_latency": self._average(all_read_latencies),
            "average_authoritative_read_latency": self._average(authoritative_latencies),
            "average_speculative_read_latency": self._average(speculative_latencies),
            "average_local_hit_latency": self._average(local_hit_latencies),

            "switch_enqueues": self.switch_enqueues,
            "switch_processes": self.switch_processes,
            "switch_max_queue_depth": self.switch_max_queue_depth,

            "average_speculative_data_arrival_latency": self._average(spec_data_latencies),
            "average_speculative_head_start": self._average(spec_head_start_latencies),
        }

    def print_report(self):
        summary = self.summary_dict()

        print()
        print("=" * 80)
        print("STATS REPORT")
        print("=" * 80)

        print()
        print("[Instruction Counts]")
        print(f"  Total reads:  {summary['total_reads']}")
        print(f"  Total writes: {summary['total_writes']}")

        print()
        print("[Cache Behavior]")
        print(f"  Local cache hits:   {summary['local_cache_hits']}")
        print(f"  Local cache misses: {summary['local_cache_misses']}")

        print()
        print("[Read Completion]")
        print(f"  Authoritative reads completed: {summary['authoritative_reads_completed']}")
        print(f"  Speculative reads completed:   {summary['speculative_reads_completed']}")
        print(f"  Average read latency:          {summary['average_read_latency']:.2f} cycles")
        print(f"  Average authoritative latency: {summary['average_authoritative_read_latency']:.2f} cycles")
        print(f"  Average speculative latency:   {summary['average_speculative_read_latency']:.2f} cycles")
        print(f"  Average local-hit latency:     {summary['average_local_hit_latency']:.2f} cycles")

        print()
        print("[Speculation]")
        print(f"  Speculative attempts:     {summary['speculative_attempts']}")
        print(f"  Speculative successes:    {summary['speculative_successes']}")
        print(f"  Speculative failures:     {summary['speculative_failures']}")
        print(f"  Speculative squashes:     {summary['speculative_squashes']}")
        print(f"  Speculative success rate: {summary['speculative_success_rate'] * 100:.2f}%")

        print()
        print("[Coherence]")
        print(f"  Validation successes:       {summary['validation_successes']}")
        print(f"  Validation failures:        {summary['validation_failures']}")
        print(f"  Exclusive requests:         {summary['exclusive_requests']}")
        print(f"  Exclusive grants:           {summary['exclusive_grants']}")
        print(f"  Invalidations sent:         {summary['invalidations_sent']}")
        print(f"  Invalidations acknowledged: {summary['invalidations_acknowledged']}")

        print()
        print("[Network]")
        print(f"  Messages created:        {summary['messages_created']}")
        print(f"  Messages completed:      {summary['messages_completed']}")
        print(f"  Average path distance:   {summary['average_path_distance']:.2f} hops")

        print()
        print("[Switch Queue Depths]")
        all_switches = sorted(summary["switch_max_queue_depth"].keys())
        if not all_switches:
            print("  No switch queue activity recorded.")
        else:
            for switch_id in all_switches:
                max_depth = summary["switch_max_queue_depth"].get(switch_id, 0)
                enqueues = summary["switch_enqueues"].get(switch_id, 0)
                processes = summary["switch_processes"].get(switch_id, 0)
                print(
                    f"  {switch_id}: max_queue_depth={max_depth}, "
                    f"enqueues={enqueues}, processed={processes}"
                )