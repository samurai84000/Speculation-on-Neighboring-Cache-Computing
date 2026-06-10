class CycleLogger:
    def __init__(self):
        self.cycles = {}

    def start_cycle(self, cycle):
        if cycle not in self.cycles:
            self.cycles[cycle] = {
                "processor_behavior": [],
                "cache_behavior": [],
                "switch_behavior": [],
                "directory_behavior": [],
                "network_behavior": [],
            }

    def log_processor(self, cycle, message):
        self.start_cycle(cycle)
        self.cycles[cycle]["processor_behavior"].append(message)

    def log_cache(self, cycle, message):
        self.start_cycle(cycle)
        self.cycles[cycle]["cache_behavior"].append(message)

    def log_switch(self, cycle, message):
        self.start_cycle(cycle)
        self.cycles[cycle]["switch_behavior"].append(message)

    def log_directory(self, cycle, message):
        self.start_cycle(cycle)
        self.cycles[cycle]["directory_behavior"].append(message)

    def log_network(self, cycle, message):
        self.start_cycle(cycle)
        self.cycles[cycle]["network_behavior"].append(message)

    def print_cycle(self, cycle):
        data = self.cycles.get(cycle)

        if data is None:
            print(f"No data for cycle {cycle}")
            return

        print("=" * 80)
        print(f"CLOCK CYCLE {cycle}")
        print("=" * 80)

        sections = [
            ("Processor Behavior", "processor_behavior"),
            ("Cache Behavior", "cache_behavior"),
            ("Switch Behavior", "switch_behavior"),
            ("Directory Behavior", "directory_behavior"),
            ("Network Behavior", "network_behavior"),
        ]

        for title, key in sections:
            print(f"\n[{title}]")
            if data[key]:
                for line in data[key]:
                    print(f"  - {line}")
            else:
                print(f"  - No {title.lower()}")

        print()

    def print_all_cycles(self):
        for cycle in sorted(self.cycles.keys()):
            self.print_cycle(cycle)