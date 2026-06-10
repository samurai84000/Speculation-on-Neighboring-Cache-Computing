import csv
import re
from pathlib import Path

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    PLOTTING_AVAILABLE = True
    PLOTTING_IMPORT_ERROR = None
except Exception as exc:
    PLOTTING_AVAILABLE = False
    PLOTTING_IMPORT_ERROR = exc

from network import Network
from simulator_with_stats import ClockedSimulator
from instruction_loader import InstructionLoader


# =============================================================================
# Network construction
# =============================================================================

def build_network(num_nodes, blocks_per_cache, enable_express_lanes):
    network = Network()

    network.generate_processor_nodes(
        num_nodes=num_nodes,
        blocks_per_cache=blocks_per_cache
    )

    network.build_binary_tree()

    if enable_express_lanes:
        network.add_mirror_express_lanes()

    network.initialize_directory_state_from_caches()

    return network


# =============================================================================
# Network diagram generation
# =============================================================================

def numeric_id(node_id):
    """
    Sort IDs like P1, P2, S0, S10 numerically instead of alphabetically.
    """
    digits = "".join(ch for ch in str(node_id) if ch.isdigit())

    if digits:
        return int(digits)

    return 0


def get_switch_levels(network):
    """
    Returns switch levels as a list of lists ordered from bottom to top.

    The Network object usually exposes switch_levels as either:
      - {0: [bottom switches], 1: [...], ...}
      - [[bottom switches], [...], ...]
    """
    if not hasattr(network, "switch_levels"):
        return []

    switch_levels = network.switch_levels

    if isinstance(switch_levels, dict):
        return [
            sorted(switch_levels[level], key=numeric_id)
            for level in sorted(switch_levels.keys())
        ]

    if isinstance(switch_levels, list):
        return [
            sorted(level, key=numeric_id)
            for level in switch_levels
        ]

    return []


def normalize_link_type(link_type):
    """
    Normalizes possible link labels into either 'tree' or 'express'.
    """
    if link_type is None:
        return "tree"

    link_type = str(link_type).lower()

    if "express" in link_type:
        return "express"

    return "tree"


def extract_network_edges(network):
    """
    Extracts unique undirected edges from the Network object.

    If the Network object does not expose link metadata in a drawable format,
    this function falls back to reconstructing the binary-tree edges from the
    processor count and switch_levels. That fallback is what guarantees the
    report diagram always has visible lines.
    """
    edges = []
    seen = set()

    def add_edge(a, b, latency=1, link_type="tree"):
        if a is None or b is None:
            return

        a = str(a)
        b = str(b)

        edge_key = tuple(sorted((a, b)))

        if edge_key in seen:
            return

        seen.add(edge_key)
        edges.append((a, b, latency, normalize_link_type(link_type)))

    def edge_from_item(item, default_type="tree"):
        if not isinstance(item, tuple) and not isinstance(item, list):
            return

        if len(item) < 2:
            return

        a = item[0]
        b = item[1]
        latency = 1
        link_type = default_type

        if len(item) >= 3:
            third = item[2]

            if isinstance(third, dict):
                latency = third.get("latency", 1)
                link_type = third.get("type", third.get("link_type", default_type))
            elif isinstance(third, str):
                link_type = third
            else:
                latency = third

        if len(item) >= 4:
            link_type = item[3]

        add_edge(a, b, latency, link_type)

    # Common case: network.links exists.
    if hasattr(network, "links"):
        links = network.links

        if isinstance(links, dict):
            for key, value in links.items():
                # Format: {(a, b): metadata}
                if isinstance(key, tuple) and len(key) >= 2:
                    metadata = value if isinstance(value, dict) else {}
                    add_edge(
                        key[0],
                        key[1],
                        metadata.get("latency", 1),
                        metadata.get("type", metadata.get("link_type", "tree"))
                    )

                # Format: {a: {b: metadata}}
                elif isinstance(value, dict):
                    a = key

                    for b, metadata in value.items():
                        if not isinstance(metadata, dict):
                            metadata = {}

                        add_edge(
                            a,
                            b,
                            metadata.get("latency", 1),
                            metadata.get("type", metadata.get("link_type", "tree"))
                        )

        elif isinstance(links, list):
            for item in links:
                edge_from_item(item)

    # Optional explicit edge lists.
    for attr_name, default_type in [
        ("tree_links", "tree"),
        ("express_links", "express"),
        ("express_lanes", "express"),
    ]:
        if hasattr(network, attr_name):
            for item in getattr(network, attr_name):
                edge_from_item(item, default_type=default_type)

    # Fallback: reconstruct the topology from processor IDs and switch levels.
    # This is used when network.py can route messages internally but does not
    # expose its links in network.links/tree_links/express_links.
    if not edges:
        add_inferred_binary_tree_edges(network, add_edge)

    return edges


def add_inferred_binary_tree_edges(network, add_edge):
    """
    Reconstructs drawable edges for the generated binary tree.

    Assumptions match this simulator's topology generator:
      - processors P1..PN are leaves
      - level 0 switches are bottom switches
      - each bottom switch owns two processors
      - each higher-level switch owns two switches from the level below
      - express lanes mirror bottom switches: S0<->S(last), S1<->S(last-1), ...
    """
    processor_ids = sorted(
        [str(processor_id) for processor_id in network.nodes.keys()],
        key=numeric_id
    )

    switch_levels = get_switch_levels(network)

    if not processor_ids or not switch_levels:
        return

    bottom_switches = [str(switch_id) for switch_id in switch_levels[0]]

    # Processor-to-bottom-switch edges.
    # For 8 processors: P1/P2->S0, P3/P4->S1, P5/P6->S2, P7/P8->S3.
    for index, processor_id in enumerate(processor_ids):
        bottom_index = min(index // 2, len(bottom_switches) - 1)
        add_edge(processor_id, bottom_switches[bottom_index], 1, "tree")

    # Switch-to-switch tree edges.
    # Each parent at level L+1 connects to two children at level L.
    for level_index in range(len(switch_levels) - 1):
        children = [str(switch_id) for switch_id in switch_levels[level_index]]
        parents = [str(switch_id) for switch_id in switch_levels[level_index + 1]]

        for child_index, child_id in enumerate(children):
            parent_index = min(child_index // 2, len(parents) - 1)
            add_edge(child_id, parents[parent_index], 1, "tree")

    # Express lanes only exist if the generated network has an express-lane
    # indicator. Different versions use different names, so check several.
    has_express = False

    for attr_name in ["express_lanes", "express_links"]:
        if hasattr(network, attr_name) and getattr(network, attr_name):
            has_express = True

    if hasattr(network, "enable_express_lanes") and network.enable_express_lanes:
        has_express = True

    # Some versions only add express edges internally and expose no attribute.
    # If the caller title says express lanes, draw_network_diagram will pass a
    # marker onto the network before extracting edges.
    if hasattr(network, "_force_draw_express_lanes"):
        has_express = True

    if has_express:
        half = len(bottom_switches) // 2

        for i in range(half):
            left = bottom_switches[i]
            right = bottom_switches[len(bottom_switches) - 1 - i]

            if left != right:
                add_edge(left, right, 1, "express")


def get_network_positions(network):
    """
    Creates fixed report-friendly positions for processors and switches.

    Processors are on the bottom row.
    Bottom-level switches are above processors.
    Higher-level switches are placed above that.
    """
    positions = {}

    processor_ids = sorted(
        [str(processor_id) for processor_id in network.nodes.keys()],
        key=numeric_id
    )

    for index, processor_id in enumerate(processor_ids):
        positions[processor_id] = (index, 0)

    switch_levels = get_switch_levels(network)

    if switch_levels:
        processor_width = max(len(processor_ids) - 1, 1)

        for level_index, switch_ids in enumerate(switch_levels):
            y = level_index + 1
            switch_ids = [str(switch_id) for switch_id in switch_ids]

            if len(switch_ids) == 1:
                x_positions = [processor_width / 2]
            else:
                step = processor_width / (len(switch_ids) - 1)
                x_positions = [
                    index * step
                    for index in range(len(switch_ids))
                ]

            for switch_id, x in zip(switch_ids, x_positions):
                positions[switch_id] = (x, y)

    elif hasattr(network, "switches"):
        switch_ids = sorted(
            [str(switch_id) for switch_id in network.switches.keys()],
            key=numeric_id
        )

        for index, switch_id in enumerate(switch_ids):
            positions[switch_id] = (index, 1)

    return positions


def draw_network_diagram(network, output_file, title):
    """
    Saves a PNG diagram of the generated network.

    Tree links are solid.
    Express lanes are dashed.
    Processor nodes are circles.
    Switch nodes are squares.
    """
    if not PLOTTING_AVAILABLE:
        print(f"Matplotlib unavailable, skipping network diagram: {PLOTTING_IMPORT_ERROR}")
        return

    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    positions = get_network_positions(network)
    edges = extract_network_edges(network)

    if not positions:
        print(f"No node positions found, skipping network diagram: {output_file}")
        return

    plt.figure(figsize=(14, 7))

    for a, b, latency, link_type in edges:
        if a not in positions or b not in positions:
            continue

        x1, y1 = positions[a]
        x2, y2 = positions[b]

        linestyle = "--" if link_type == "express" else "-"
        linewidth = 2.6 if link_type == "express" else 1.6

        plt.plot(
            [x1, x2],
            [y1, y2],
            linestyle=linestyle,
            linewidth=linewidth
        )

    for processor_id in sorted(network.nodes.keys(), key=numeric_id):
        processor_id = str(processor_id)

        if processor_id not in positions:
            continue

        x, y = positions[processor_id]

        plt.scatter(
            [x],
            [y],
            marker="o",
            s=900,
            edgecolors="black",
            linewidths=1.5,
            zorder=3
        )

        plt.text(
            x,
            y,
            processor_id,
            ha="center",
            va="center",
            fontsize=10,
            zorder=4
        )

    for switch_id in sorted(network.switches.keys(), key=numeric_id):
        switch_id = str(switch_id)

        if switch_id not in positions:
            continue

        x, y = positions[switch_id]

        plt.scatter(
            [x],
            [y],
            marker="s",
            s=900,
            edgecolors="black",
            linewidths=1.5,
            zorder=3
        )

        plt.text(
            x,
            y,
            switch_id,
            ha="center",
            va="center",
            fontsize=10,
            zorder=4
        )

    plt.title(title)
    plt.axis("off")
    plt.tight_layout()
    plt.savefig(output_file, dpi=250)
    plt.close()

    print(f"Saved network diagram: {output_file}")


def generate_network_diagrams_for_report(num_nodes, blocks_per_cache, output_dir):
    """
    Generates report-ready diagrams:
      1. Baseline binary tree
      2. Binary tree with mirror express lanes
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    baseline_network = build_network(
        num_nodes=num_nodes,
        blocks_per_cache=blocks_per_cache,
        enable_express_lanes=False
    )

    draw_network_diagram(
        network=baseline_network,
        output_file=output_dir / f"baseline_binary_tree_{num_nodes}_processors.png",
        title=f"Baseline Binary Tree Network ({num_nodes} Processors)"
    )

    express_network = build_network(
        num_nodes=num_nodes,
        blocks_per_cache=blocks_per_cache,
        enable_express_lanes=True
    )
    express_network._force_draw_express_lanes = True

    draw_network_diagram(
        network=express_network,
        output_file=output_dir / f"express_lane_tree_{num_nodes}_processors.png",
        title=f"Binary Tree with Mirror Express Lanes ({num_nodes} Processors)"
    )


# =============================================================================
# Test file management
# =============================================================================

def ensure_instruction_tests_exist():
    """
    Creates a delayed speculation test if it does not already exist.

    This test is important because it lets P1 finish receiving the block
    before P2 tries to speculate from it, even when express lanes are disabled.
    """
    test_dir = Path("instruction_tests")
    test_dir.mkdir(parents=True, exist_ok=True)

    delayed_test = test_dir / "remote_home_delayed_speculation_success.txt"

    if not delayed_test.exists():
        delayed_test.write_text(
            "# remote_home_delayed_speculation_success.txt\n"
            "# Purpose:\n"
            "#   Let P1 fetch a remote-home block first, then much later let P2\n"
            "#   read the same address so speculation can trigger even without\n"
            "#   express lanes.\n"
            "#\n"
            "# Assumption:\n"
            "#   P1 and P2 are local neighbors under S0.\n"
            "#   Address 31 maps to a far bottom-level home switch as N grows.\n"
            "\n"
            "0 P1 READ 31\n"
            "60 P2 READ 31\n"
        )


def get_instruction_test_files():
    """
    Add/remove files here as you create more instruction tests.
    Each file will be run across all network sizes and all 4 configurations.
    """
    test_files = [
        "remote_home_local_speculation_success.txt",
        "remote_home_authoritative_reads.txt",
        "high_contention_speculation_stress.txt",
        "root_queue_contention_stress.txt",
    ]

    existing_files = []

    for file_name in test_files:
        path = Path(file_name)

        if path.exists():
            existing_files.append(path)
        else:
            print(f"WARNING: missing instruction file, skipping: {file_name}")

    return existing_files


# =============================================================================
# Utility helpers
# =============================================================================

def safe_slug(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = text.strip("_")
    return text


def cycles_for_test(num_nodes, instruction_file):
    """
    Gives larger networks and stress tests more cycles to finish.
    Adjust these numbers if you see messages not completing.
    """
    name = instruction_file.name.lower()

    if "contention" in name or "stress" in name:
        cycle_map = {
            8: 160,
            16: 240,
            32: 360,
            64: 520,
        }
    elif "delayed" in name:
        cycle_map = {
            8: 120,
            16: 180,
            32: 260,
            64: 380,
        }
    else:
        cycle_map = {
            8: 100,
            16: 160,
            32: 240,
            64: 340,
        }

    return cycle_map.get(num_nodes, max(100, num_nodes * 8))


def max_queue_depth_from_summary(summary):
    switch_max_depths = summary.get("switch_max_queue_depth", {})

    if not switch_max_depths:
        return 0

    return max(switch_max_depths.values())


# =============================================================================
# CSV result formatting
# =============================================================================

def flatten_summary_for_csv(test_name, instruction_file, processor_count, experiment_name, summary):
    max_queue_depth = max_queue_depth_from_summary(summary)

    return {
        "test_name": test_name,
        "instruction_file": str(instruction_file),
        "processor_count": processor_count,
        "experiment": experiment_name,

        "total_reads": summary.get("total_reads", 0),
        "total_writes": summary.get("total_writes", 0),

        "local_cache_hits": summary.get("local_cache_hits", 0),
        "local_cache_misses": summary.get("local_cache_misses", 0),

        "authoritative_reads_completed": summary.get(
            "authoritative_reads_completed", 0
        ),
        "speculative_reads_completed": summary.get(
            "speculative_reads_completed", 0
        ),

        "speculative_attempts": summary.get("speculative_attempts", 0),
        "speculative_successes": summary.get("speculative_successes", 0),
        "speculative_failures": summary.get("speculative_failures", 0),
        "speculative_squashes": summary.get("speculative_squashes", 0),
        "speculative_success_rate_percent": (
            summary.get("speculative_success_rate", 0.0) * 100.0
        ),

        "validation_successes": summary.get("validation_successes", 0),
        "validation_failures": summary.get("validation_failures", 0),

        "exclusive_requests": summary.get("exclusive_requests", 0),
        "exclusive_grants": summary.get("exclusive_grants", 0),
        "invalidations_sent": summary.get("invalidations_sent", 0),
        "invalidations_acknowledged": summary.get(
            "invalidations_acknowledged", 0
        ),

        "messages_created": summary.get("messages_created", 0),
        "messages_completed": summary.get("messages_completed", 0),
        "average_path_distance": summary.get("average_path_distance", 0.0),

        "average_read_latency": summary.get("average_read_latency", 0.0),
        "average_authoritative_read_latency": summary.get(
            "average_authoritative_read_latency", 0.0
        ),
        "average_speculative_read_latency": summary.get(
            "average_speculative_read_latency", 0.0
        ),
        "average_local_hit_latency": summary.get(
            "average_local_hit_latency", 0.0
        ),

        # New speculation timing metrics
        "average_speculative_data_arrival_latency": summary.get(
            "average_speculative_data_arrival_latency", 0.0
        ),
        "average_speculative_head_start": summary.get(
            "average_speculative_head_start", 0.0
        ),

        "max_queue_depth": max_queue_depth,
    }

def find_row(rows, processor_count, experiment_name):
    for row in rows:
        if (
            int(row["processor_count"]) == int(processor_count)
            and row["experiment"] == experiment_name
        ):
            return row

    return None


def build_speculation_savings_rows(rows):
    """
    Builds derived rows for cycles saved by speculative computation.

    For no-express comparison:
        Baseline Binary Tree vs Speculation Only

    For express-lane comparison:
        Express Lanes Only vs Full Optimized

    Cycles saved means:
        non_spec_authoritative_latency - speculative_data_arrival_latency

    This measures how many cycles earlier the processor can begin computing
    because speculative data arrived before the normal authoritative path.
    """
    processor_counts = sorted(
        {
            int(row["processor_count"])
            for row in rows
        }
    )

    savings_rows = []

    for processor_count in processor_counts:
        baseline = find_row(
            rows=rows,
            processor_count=processor_count,
            experiment_name="Baseline Binary Tree"
        )

        speculation_only = find_row(
            rows=rows,
            processor_count=processor_count,
            experiment_name="Speculation Only"
        )

        express_only = find_row(
            rows=rows,
            processor_count=processor_count,
            experiment_name="Express Lanes Only"
        )

        full_optimized = find_row(
            rows=rows,
            processor_count=processor_count,
            experiment_name="Full Optimized"
        )

        if baseline is not None and speculation_only is not None:
            spec_attempts = int(float(speculation_only.get("speculative_attempts", 0)))
            spec_data_latency = float(
                speculation_only.get("average_speculative_data_arrival_latency", 0.0)
            )
            baseline_latency = float(
                baseline.get("average_authoritative_read_latency", 0.0)
            )

            if spec_attempts > 0 and spec_data_latency > 0:
                cycles_saved = max(0.0, baseline_latency - spec_data_latency)
            else:
                cycles_saved = 0.0

            savings_rows.append(
                {
                    "processor_count": processor_count,
                    "comparison": "Speculation Only vs Baseline",
                    "cycles_saved": cycles_saved,
                }
            )

        if express_only is not None and full_optimized is not None:
            spec_attempts = int(float(full_optimized.get("speculative_attempts", 0)))
            spec_data_latency = float(
                full_optimized.get("average_speculative_data_arrival_latency", 0.0)
            )
            express_latency = float(
                express_only.get("average_authoritative_read_latency", 0.0)
            )

            if spec_attempts > 0 and spec_data_latency > 0:
                cycles_saved = max(0.0, express_latency - spec_data_latency)
            else:
                cycles_saved = 0.0

            savings_rows.append(
                {
                    "processor_count": processor_count,
                    "comparison": "Full Optimized vs Express Only",
                    "cycles_saved": cycles_saved,
                }
            )

    return savings_rows


def make_speculation_savings_line_plot(rows, output_path):
    savings_rows = build_speculation_savings_rows(rows)

    if not savings_rows:
        return

    comparison_names = []

    for row in savings_rows:
        comparison_name = row["comparison"]

        if comparison_name not in comparison_names:
            comparison_names.append(comparison_name)

    plt.figure(figsize=(11, 6))

    for comparison_name in comparison_names:
        comparison_rows = [
            row for row in savings_rows
            if row["comparison"] == comparison_name
        ]

        comparison_rows.sort(key=lambda row: int(row["processor_count"]))

        x_values = [
            int(row["processor_count"])
            for row in comparison_rows
        ]

        y_values = [
            float(row["cycles_saved"])
            for row in comparison_rows
        ]

        plt.plot(
            x_values,
            y_values,
            marker="o",
            label=comparison_name
        )

    plt.xlabel("Processor count")
    plt.ylabel("Cycles saved")
    plt.title("Cycles Saved by Speculative Computing vs Network Size")
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_path, dpi=200)
    plt.close()

def write_rows_csv(rows, output_file):
    if not rows:
        print(f"No rows to write for {output_file}")
        return

    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = list(rows[0].keys())

    with output_file.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Saved CSV: {output_file}")


# =============================================================================
# Plotting
# =============================================================================

def make_scaling_line_plot(rows, metric, ylabel, title, output_path):
    experiment_names = []

    for row in rows:
        experiment_name = row["experiment"]

        if experiment_name not in experiment_names:
            experiment_names.append(experiment_name)

    plt.figure(figsize=(11, 6))

    for experiment_name in experiment_names:
        experiment_rows = [
            row for row in rows
            if row["experiment"] == experiment_name
        ]

        experiment_rows.sort(key=lambda row: int(row["processor_count"]))

        x_values = [
            int(row["processor_count"])
            for row in experiment_rows
        ]

        y_values = [
            float(row.get(metric, 0.0))
            for row in experiment_rows
        ]

        plt.plot(
            x_values,
            y_values,
            marker="o",
            label=experiment_name
        )

    plt.xlabel("Processor count")
    plt.ylabel(ylabel)
    plt.title(title)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_path, dpi=200)
    plt.close()


def make_grouped_bar_plot_for_size(rows, processor_count, metric, ylabel, title, output_path):
    size_rows = [
        row for row in rows
        if int(row["processor_count"]) == processor_count
    ]

    if not size_rows:
        return

    experiment_names = [row["experiment"] for row in size_rows]
    values = [float(row.get(metric, 0.0)) for row in size_rows]

    plt.figure(figsize=(11, 6))
    plt.bar(experiment_names, values)
    plt.ylabel(ylabel)
    plt.title(title)
    plt.xticks(rotation=20, ha="right")
    plt.tight_layout()
    plt.savefig(output_path, dpi=200)
    plt.close()


def generate_plots_for_test(test_name, rows, output_dir):
    if not PLOTTING_AVAILABLE:
        print(f"Matplotlib unavailable, skipping plots: {PLOTTING_IMPORT_ERROR}")
        return

    if not rows:
        print(f"No rows available for plotting test: {test_name}")
        return

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    make_scaling_line_plot(
        rows=rows,
        metric="average_read_latency",
        ylabel="Average read latency (cycles)",
        title=f"{test_name}: Average Read Latency vs Network Size",
        output_path=output_dir / "scaling_avg_read_latency.png",
    )

    make_scaling_line_plot(
        rows=rows,
        metric="average_authoritative_read_latency",
        ylabel="Average authoritative read latency (cycles)",
        title=f"{test_name}: Average Authoritative Read Latency vs Network Size",
        output_path=output_dir / "scaling_authoritative_read_latency.png",
    )

    make_scaling_line_plot(
        rows=rows,
        metric="average_speculative_read_latency",
        ylabel="Average speculative read latency (cycles)",
        title=f"{test_name}: Average Speculative Read Latency vs Network Size",
        output_path=output_dir / "scaling_speculative_read_latency.png",
    )

    make_scaling_line_plot(
        rows=rows,
        metric="average_path_distance",
        ylabel="Average path distance (hops)",
        title=f"{test_name}: Average Message Path Distance vs Network Size",
        output_path=output_dir / "scaling_avg_path_distance.png",
    )

    make_scaling_line_plot(
        rows=rows,
        metric="max_queue_depth",
        ylabel="Maximum switch queue depth",
        title=f"{test_name}: Maximum Queue Depth vs Network Size",
        output_path=output_dir / "scaling_max_queue_depth.png",
    )

    make_scaling_line_plot(
        rows=rows,
        metric="messages_created",
        ylabel="Messages created",
        title=f"{test_name}: Messages Created vs Network Size",
        output_path=output_dir / "scaling_messages_created.png",
    )

    make_scaling_line_plot(
        rows=rows,
        metric="speculative_success_rate_percent",
        ylabel="Speculative success rate (%)",
        title=f"{test_name}: Speculative Success Rate vs Network Size",
        output_path=output_dir / "scaling_speculation_success_rate.png",
    )

    make_scaling_line_plot(
        rows=rows,
        metric="average_speculative_data_arrival_latency",
        ylabel="Speculative data arrival latency (cycles)",
        title=f"{test_name}: Speculative Data Arrival Latency vs Network Size",
        output_path=output_dir / "scaling_speculative_data_arrival_latency.png",
    )

    make_scaling_line_plot(
        rows=rows,
        metric="average_speculative_head_start",
        ylabel="Speculative head start (cycles)",
        title=f"{test_name}: Speculative Head Start vs Network Size",
        output_path=output_dir / "scaling_speculative_head_start.png",
    )

    make_speculation_savings_line_plot(
        rows=rows,
        output_path=output_dir / "scaling_cycles_saved_by_speculation.png",
    )

    # Also make one simple 64-processor bar chart for quick README use.
    if any(int(row["processor_count"]) == 64 for row in rows):
        make_grouped_bar_plot_for_size(
            rows=rows,
            processor_count=64,
            metric="average_read_latency",
            ylabel="Average read latency (cycles)",
            title=f"{test_name}: Average Read Latency at 64 Processors",
            output_path=output_dir / "bar_avg_read_latency_64.png",
        )

        make_grouped_bar_plot_for_size(
            rows=rows,
            processor_count=64,
            metric="average_path_distance",
            ylabel="Average path distance (hops)",
            title=f"{test_name}: Average Path Distance at 64 Processors",
            output_path=output_dir / "bar_avg_path_distance_64.png",
        )

    print(f"Saved plots for {test_name}: {output_dir}")



# =============================================================================
# Running experiments
# =============================================================================

def run_experiment(
    experiment_name,
    num_nodes,
    blocks_per_cache,
    instruction_file,
    num_cycles,
    enable_speculation,
    enable_express_lanes,
    print_cycle_log=False,
    print_topology=False,
    print_final_states=False,
    print_full_report=False,
):
    print()
    print("-" * 80)
    print(
        f"{experiment_name} | "
        f"N={num_nodes} | "
        f"speculation={enable_speculation} | "
        f"express_lanes={enable_express_lanes}"
    )
    print("-" * 80)

    network = build_network(
        num_nodes=num_nodes,
        blocks_per_cache=blocks_per_cache,
        enable_express_lanes=enable_express_lanes
    )

    if print_topology:
        print()
        print("Network topology:")
        network.print_topology()

    instructions_by_cycle = InstructionLoader.load(str(instruction_file))

    simulator = ClockedSimulator(
        network,
        enable_speculation=enable_speculation
    )

    for cycle in range(num_cycles):
        if cycle in instructions_by_cycle:
            for instruction in instructions_by_cycle[cycle]:
                simulator.execute_instruction(instruction)

        simulator.step()

    if print_cycle_log:
        simulator.print_log()

    if print_full_report:
        print()
        simulator.print_switch_stats()

        print()
        simulator.print_stats_report()

    if print_final_states:
        print()
        print("Final processor states:")
        for processor_id, node in network.nodes.items():
            print(processor_id, node.processor)

    summary = simulator.stats.summary_dict()

    print(
        f"Avg read={summary.get('average_read_latency', 0.0):.2f} cycles | "
        f"Avg path={summary.get('average_path_distance', 0.0):.2f} hops | "
        f"Spec attempts={summary.get('speculative_attempts', 0)} | "
        f"Spec success={summary.get('speculative_success_rate', 0.0) * 100.0:.2f}% | "
        f"Max queue={max_queue_depth_from_summary(summary)}"

    )

    return summary


def print_test_summary_table(test_name, rows):
    print()
    print("=" * 100)
    print(f"SUMMARY TABLE: {test_name}")
    print("=" * 100)

    header = (
        f"{'N':>6}"
        f"{'Experiment':<24}"
        f"{'Avg Read':>12}"
        f"{'Auth Read':>12}"
        f"{'Spec Read':>12}"
        f"{'Data Arr':>12}"
        f"{'Head Start':>12}"
        f"{'Spec Rate':>12}"
        f"{'Avg Path':>12}"
        f"{'Max Queue':>12}"
        f"{'Messages':>12}"
    )

    print(header)
    print("-" * len(header))

    sorted_rows = sorted(
        rows,
        key=lambda row: (
            int(row["processor_count"]),
            row["experiment"]
        )
    )

    for row in sorted_rows:
        print(
            f"{int(row['processor_count']):>6}"
            f"{row['experiment']:<24}"
            f"{float(row['average_read_latency']):>12.2f}"
            f"{float(row['average_authoritative_read_latency']):>12.2f}"
            f"{float(row['average_speculative_read_latency']):>12.2f}"
            f"{float(row['average_speculative_data_arrival_latency']):>12.2f}"
            f"{float(row['average_speculative_head_start']):>12.2f}"
            f"{float(row['speculative_success_rate_percent']):>11.2f}%"
            f"{float(row['average_path_distance']):>12.2f}"
            f"{int(row['max_queue_depth']):>12}"
            f"{int(row['messages_created']):>12}"
        )


# =============================================================================
# Main
# =============================================================================

def main():
    # -------------------------------------------------------------------------
    # Global configuration
    # -------------------------------------------------------------------------
    blocks_per_cache = 4

    network_sizes = [8, 16, 32, 64]

    output_root = Path("experiment_outputs")
    output_root.mkdir(parents=True, exist_ok=True)

    generate_network_diagrams_for_report(
        num_nodes=8,
        blocks_per_cache=blocks_per_cache,
        output_dir=output_root / "network_diagrams"
    )

    print_cycle_log = False
    print_topology = False
    print_final_states = False
    print_full_report = False

    experiments = [
        {
            "name": "Baseline Binary Tree",
            "enable_speculation": False,
            "enable_express_lanes": False,
        },
        {
            "name": "Express Lanes Only",
            "enable_speculation": False,
            "enable_express_lanes": True,
        },
        {
            "name": "Speculation Only",
            "enable_speculation": True,
            "enable_express_lanes": False,
        },
        {
            "name": "Full Optimized",
            "enable_speculation": True,
            "enable_express_lanes": True,
        },
    ]

    ensure_instruction_tests_exist()

    instruction_files = get_instruction_test_files()

    all_rows = []

    for instruction_file in instruction_files:
        test_name = instruction_file.stem
        test_slug = safe_slug(test_name)

        test_output_dir = output_root / test_slug
        plots_output_dir = test_output_dir / "plots"

        test_rows = []

        print()
        print("#" * 100)
        print(f"RUNNING TEST FILE: {instruction_file}")
        print("#" * 100)

        for num_nodes in network_sizes:
            num_cycles = cycles_for_test(
                num_nodes=num_nodes,
                instruction_file=instruction_file
            )

            print()
            print(f"NETWORK SIZE: {num_nodes} processors | cycles={num_cycles}")

            for experiment in experiments:
                summary = run_experiment(
                    experiment_name=experiment["name"],
                    num_nodes=num_nodes,
                    blocks_per_cache=blocks_per_cache,
                    instruction_file=instruction_file,
                    num_cycles=num_cycles,
                    enable_speculation=experiment["enable_speculation"],
                    enable_express_lanes=experiment["enable_express_lanes"],
                    print_cycle_log=print_cycle_log,
                    print_topology=print_topology,
                    print_final_states=print_final_states,
                    print_full_report=print_full_report,
                )

                row = flatten_summary_for_csv(
                    test_name=test_name,
                    instruction_file=instruction_file,
                    processor_count=num_nodes,
                    experiment_name=experiment["name"],
                    summary=summary
                )

                test_rows.append(row)
                all_rows.append(row)

        print_test_summary_table(test_name, test_rows)

        write_rows_csv(
            rows=test_rows,
            output_file=test_output_dir / "results.csv"
        )

        generate_plots_for_test(
            test_name=test_name,
            rows=test_rows,
            output_dir=plots_output_dir
        )

    write_rows_csv(
        rows=all_rows,
        output_file=output_root / "all_results.csv"
    )

    print()
    print("=" * 100)
    print("ALL TESTS COMPLETE")
    print("=" * 100)
    print(f"Output folder: {output_root.resolve()}")
    print()
    print("Each test has its own folder:")
    print("  experiment_outputs/<test_name>/results.csv")
    print("  experiment_outputs/<test_name>/plots/*.png")
    print()
    print("Combined CSV:")
    print("  experiment_outputs/all_results.csv")


if __name__ == "__main__":
    main()