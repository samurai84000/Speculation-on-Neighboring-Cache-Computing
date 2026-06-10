from node import Node
from switch import Switch
from cache_state import CacheState


class Network:
    def __init__(self):
        self.nodes = {}
        self.switches = {}
        self.edges = {}

        self.root_switch_id = None
        self.switch_levels = []

    def add_processor_node(self, node):
        self.nodes[node.node_id] = node
        self.edges.setdefault(node.node_id, [])

    def add_switch(self, switch):
        self.switches[switch.switch_id] = switch
        self.edges.setdefault(switch.switch_id, [])

    def add_link(self, a, b, latency=1, link_type="tree"):
        self.edges.setdefault(a, [])
        self.edges.setdefault(b, [])

        self.edges[a].append({
            "target": b,
            "latency": latency,
            "type": link_type
        })

        self.edges[b].append({
            "target": a,
            "latency": latency,
            "type": link_type
        })

    def has_link(self, a, b):
        return any(edge["target"] == b for edge in self.edges.get(a, []))

    def remove_link(self, a, b):
        self.edges[a] = [
            edge for edge in self.edges[a]
            if edge["target"] != b
        ]

        self.edges[b] = [
            edge for edge in self.edges[b]
            if edge["target"] != a
        ]

    def generate_processor_nodes(self, num_nodes, blocks_per_cache):
        for i in range(num_nodes):
            node_id = f"P{i + 1}"
            node = Node(node_id=node_id, cache_size=blocks_per_cache)

            start_address = i * blocks_per_cache
            end_address = start_address + blocks_per_cache

            for address in range(start_address, end_address):
                node.cache.write(
                    address=address,
                    data=f"Data_{address}",
                    state=CacheState.SHARED,
                    version=0
                )

            self.add_processor_node(node)

    def build_binary_tree(self):
        current_level = list(self.nodes.keys())
        switch_count = 0
        self.switch_levels = []

        while len(current_level) > 1:
            next_level = []
            switches_created_this_level = []

            for i in range(0, len(current_level), 2):
                left = current_level[i]

                if i + 1 < len(current_level):
                    right = current_level[i + 1]

                    switch_id = f"S{switch_count}"
                    switch_count += 1

                    switch = Switch(switch_id)
                    self.add_switch(switch)

                    self.add_link(switch_id, left, latency=1, link_type="tree")
                    self.add_link(switch_id, right, latency=1, link_type="tree")

                    next_level.append(switch_id)
                    switches_created_this_level.append(switch_id)

                else:
                    next_level.append(left)

            if switches_created_this_level:
                self.switch_levels.append(switches_created_this_level)

            current_level = next_level

        self.root_switch_id = current_level[0]

    def add_mirror_express_lanes(self, latency=1):
        if not self.switch_levels:
            raise ValueError("Binary tree must be built before adding express lanes.")

        bottom_switches = self.switch_levels[0]
        chosen_lanes = []

        left = 0
        right = len(bottom_switches) - 1

        while left < right:
            a = bottom_switches[left]
            b = bottom_switches[right]

            if not self.has_link(a, b):
                self.add_link(a, b, latency=latency, link_type="express")
                chosen_lanes.append((a, b))

            left += 1
            right -= 1

        return chosen_lanes

    def get_local_switch_for_processor(self, processor_id):
        for edge in self.edges.get(processor_id, []):
            target = edge["target"]
            if target in self.switches:
                return target

        return None

    def get_home_switch_for_address(self, address):
        if not self.switch_levels:
            raise ValueError("Build binary tree before asking for home switches.")

        bottom_switches = self.switch_levels[0]

        # Simple first mapping.
        # This distributes addresses across bottom-level home switches.
        home_index = address % len(bottom_switches)
        return bottom_switches[home_index]

    def initialize_directory_state_from_caches(self):
        for processor_id, node in self.nodes.items():
            local_switch_id = self.get_local_switch_for_processor(processor_id)

            if local_switch_id is None:
                continue

            local_switch = self.switches[local_switch_id]

            for address, line in node.cache.lines.items():
                if not line.is_valid():
                    continue

                local_switch.register_cache_line(
                    processor_id=processor_id,
                    address=address,
                    state=line.state,
                    version=line.version
                )

                home_switch_id = self.get_home_switch_for_address(address)
                home_switch = self.switches[home_switch_id]

                home_switch.register_home_sharer(
                    address=address,
                    processor_id=processor_id,
                    version=line.version
                )

    def register_installed_cache_line(self, processor_id, address, state, version):
        local_switch_id = self.get_local_switch_for_processor(processor_id)

        if local_switch_id is not None:
            local_switch = self.switches[local_switch_id]
            local_switch.register_cache_line(
                processor_id=processor_id,
                address=address,
                state=state,
                version=version
            )

    def shortest_path(self, start, end):
        unvisited = set(self.edges.keys())
        distances = {node_id: float("inf") for node_id in self.edges}
        previous = {node_id: None for node_id in self.edges}

        distances[start] = 0

        while unvisited:
            current = min(unvisited, key=lambda node_id: distances[node_id])

            if current == end:
                break

            if distances[current] == float("inf"):
                break

            unvisited.remove(current)

            for edge in self.edges[current]:
                neighbor = edge["target"]

                if neighbor not in unvisited:
                    continue

                new_distance = distances[current] + edge["latency"]

                if new_distance < distances[neighbor]:
                    distances[neighbor] = new_distance
                    previous[neighbor] = current

        path = []
        current = end

        while current is not None:
            path.append(current)
            current = previous[current]

        path.reverse()

        return path, distances[end]

    def print_topology(self):
        print("Processor Nodes:")
        for node_id in self.nodes:
            print(f"  {node_id}")

        print("\nSwitches:")
        for switch_id in self.switches:
            print(f"  {switch_id}")

        print("\nSwitch Levels:")
        for level_index, level in enumerate(self.switch_levels):
            print(f"  Level {level_index}: {level}")

        print("\nLinks:")
        printed = set()

        for source, edge_list in self.edges.items():
            for edge in edge_list:
                target = edge["target"]
                latency = edge["latency"]
                link_type = edge["type"]

                link_key = tuple(sorted([source, target]))

                if link_key in printed:
                    continue

                printed.add(link_key)

                print(
                    f"  {source} <--> {target} "
                    f"(latency={latency}, type={link_type})"
                )
    def unregister_cache_line(self, processor_id, address):
        local_switch_id = self.get_local_switch_for_processor(processor_id)

        if local_switch_id is not None:
            local_switch = self.switches[local_switch_id]
            local_switch.unregister_cache_line(
                processor_id=processor_id,
                address=address
            )