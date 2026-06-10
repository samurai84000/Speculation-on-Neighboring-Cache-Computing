import matplotlib.pyplot as plt


class NetworkVisualizer:
    def __init__(self, network):
        self.network = network
        self.positions = {}

    def _get_tree_neighbors(self, node_id):
        """
        Return only tree-linked neighbors.
        """
        neighbors = []
        for edge in self.network.edges.get(node_id, []):
            if edge["type"] == "tree":
                neighbors.append(edge["target"])
        return neighbors

    def _build_rooted_tree(self, current, parent=None):
        """
        Build a rooted tree structure from the undirected tree links.
        Returns:
            {
                "id": current,
                "children": [subtree1, subtree2, ...]
            }
        """
        children = []
        for neighbor in self._get_tree_neighbors(current):
            if neighbor == parent:
                continue
            children.append(self._build_rooted_tree(neighbor, current))

        return {
            "id": current,
            "children": children
        }

    def _assign_positions(self, tree, depth=0, x_offset=0):
        """
        Recursively assign positions to each node in the tree.

        Leaves get consecutive x positions.
        Internal nodes are centered above their children.
        """
        children = tree["children"]
        node_id = tree["id"]

        if not children:
            self.positions[node_id] = (x_offset, -depth)
            return x_offset + 1, x_offset

        child_centers = []
        next_x = x_offset

        for child in children:
            next_x, child_center = self._assign_positions(child, depth + 1, next_x)
            child_centers.append(child_center)

        center_x = sum(child_centers) / len(child_centers)
        self.positions[node_id] = (center_x, -depth)

        return next_x, center_x

    def compute_positions(self):
        """
        Compute positions for all nodes using the binary tree layout.
        """
        self.positions = {}

        if self.network.root_switch_id is None:
            raise ValueError("Network does not have a root switch. Build the binary tree first.")

        rooted_tree = self._build_rooted_tree(self.network.root_switch_id)
        self._assign_positions(rooted_tree)

    def draw(self, show_labels=True, figsize=(12, 8)):
        """
        Draw the network.
        """
        self.compute_positions()

        plt.figure(figsize=figsize)

        drawn_links = set()

        # Draw edges first
        for source, edge_list in self.network.edges.items():
            for edge in edge_list:
                target = edge["target"]
                link_type = edge["type"]

                link_key = tuple(sorted((source, target)))
                if link_key in drawn_links:
                    continue
                drawn_links.add(link_key)

                x1, y1 = self.positions[source]
                x2, y2 = self.positions[target]

                if link_type == "tree":
                    plt.plot([x1, x2], [y1, y2], linewidth=2)
                elif link_type == "express":
                    plt.plot([x1, x2], [y1, y2], linestyle="--", linewidth=2, color="red")
                else:
                    plt.plot([x1, x2], [y1, y2], linestyle=":", linewidth=1)

        # Draw processor nodes
        for node_id in self.network.nodes:
            x, y = self.positions[node_id]
            plt.scatter(x, y, s=500, marker="o")

            if show_labels:
                plt.text(x, y, node_id, ha="center", va="center")

        # Draw switch nodes
        for switch_id in self.network.switches:
            x, y = self.positions[switch_id]
            plt.scatter(x, y, s=500, marker="s")

            if show_labels:
                plt.text(x, y, switch_id, ha="center", va="center")

        # Legend
        plt.plot([], [], linewidth=2, label="Tree Link")
        plt.plot([], [], linestyle="--", linewidth=2, color="red", label="Express Lane")
        plt.scatter([], [], s=500, marker="o", label="Processor Node")
        plt.scatter([], [], s=500, marker="s", label="Switch")

        plt.legend()
        plt.title("Express-Lane Binary Tree Network")
        plt.axis("off")
        plt.tight_layout()
        plt.show()