# Add these helper functions to Main.py if you want CSV export.
#
# Required import at the top of Main.py:
#   import csv
#
# Then call:
#   write_results_csv(results, "experiment_results.csv")
#
# after print_comparison_table(results).


def flatten_summary_for_csv(experiment_name, summary):
    switch_max_depths = summary.get("switch_max_queue_depth", {})
    max_queue_depth = 0

    if switch_max_depths:
        max_queue_depth = max(switch_max_depths.values())

    return {
        "experiment": experiment_name,
        "total_reads": summary.get("total_reads", 0),
        "total_writes": summary.get("total_writes", 0),
        "local_cache_hits": summary.get("local_cache_hits", 0),
        "local_cache_misses": summary.get("local_cache_misses", 0),
        "authoritative_reads_completed": summary.get("authoritative_reads_completed", 0),
        "speculative_reads_completed": summary.get("speculative_reads_completed", 0),
        "speculative_attempts": summary.get("speculative_attempts", 0),
        "speculative_successes": summary.get("speculative_successes", 0),
        "speculative_failures": summary.get("speculative_failures", 0),
        "speculative_squashes": summary.get("speculative_squashes", 0),
        "speculative_success_rate_percent": summary.get("speculative_success_rate", 0.0) * 100.0,
        "validation_successes": summary.get("validation_successes", 0),
        "validation_failures": summary.get("validation_failures", 0),
        "exclusive_requests": summary.get("exclusive_requests", 0),
        "exclusive_grants": summary.get("exclusive_grants", 0),
        "invalidations_sent": summary.get("invalidations_sent", 0),
        "invalidations_acknowledged": summary.get("invalidations_acknowledged", 0),
        "messages_created": summary.get("messages_created", 0),
        "messages_completed": summary.get("messages_completed", 0),
        "average_path_distance": summary.get("average_path_distance", 0.0),
        "average_read_latency": summary.get("average_read_latency", 0.0),
        "average_authoritative_read_latency": summary.get("average_authoritative_read_latency", 0.0),
        "average_speculative_read_latency": summary.get("average_speculative_read_latency", 0.0),
        "average_local_hit_latency": summary.get("average_local_hit_latency", 0.0),
        "max_queue_depth": max_queue_depth,
    }


def write_results_csv(results, output_file):
    rows = [
        flatten_summary_for_csv(experiment_name, summary)
        for experiment_name, summary in results
    ]

    if not rows:
        print("No experiment results to write.")
        return

    fieldnames = list(rows[0].keys())

    with open(output_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print()
    print(f"Saved experiment results to {output_file}")
