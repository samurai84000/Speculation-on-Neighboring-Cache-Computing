# Speculative Neighbor Cache Reads in a Directory-Based Coherence System

This project explores a proposed improvement to a directory-based cache-coherent multicore system. In a conventional directory-based system, when a processor suffers a read miss, it must contact the home directory node for the requested block. The processor cannot safely continue using that data until the block is returned through the network.

A simplified read-miss sequence is:

1. A processor node suffers a read miss.
2. The node sends a read request to the home directory for that address.
3. The home directory locates or supplies the requested data block.
4. The data block is returned to the requesting node.
5. The requesting node installs the block and begins computation.

This process can leave the processor waiting for several cycles while the request travels through the interconnect. In small multicore systems this delay may be acceptable, but as the network grows, the latency of reaching the home node can become more significant.

The central hypothesis of this project is that nearby processor nodes often operate on related or overlapping data blocks. If a neighboring cache already holds the requested block in a clean shared state, then the requesting node may be able to begin computation earlier by using that local copy speculatively.

The proposed speculative read process is:

1. A processor node suffers a read miss.
2. The processor issues a normal read request.
3. The local switch receives the request and checks its local directory summary.
4. If a neighboring leaf node under the same switch holds the requested block in a shared state, the switch sends a speculative fetch to that neighbor.
5. At the same time, the switch sends a validation request to the block’s home directory.
6. The requesting processor receives the neighboring block with a speculative header and stores the value in a speculative load buffer.
7. The processor may begin speculative computation using the received value while waiting for home validation.
8. The home directory checks whether the source cache is still a valid sharer, whether the version matches, and whether no invalidation or ownership transfer has already been ordered first.
9. If validation succeeds, the speculative value becomes a valid loaded operand and the computation may commit.
10. If validation fails, the processor flushes the speculative computation and waits for authoritative data from the home directory.

The key correctness rule is that the neighboring cache is not authoritative. A neighboring shared copy is only a fast candidate. The home directory remains responsible for global coherence, validation, ownership tracking, invalidations, and version ordering.

This design attempts to reduce apparent read latency by overlapping two actions:

* fast local retrieval from a neighboring shared cache
* slower validation through the home directory

If the validation succeeds, the processor has hidden some of the latency of the home-directory access. If validation fails, the speculative work is discarded and the system falls back to the normal directory-coherent path.

## Network Architecture

The simulated multicore system is organized as a binary-tree interconnect. Processor nodes are placed at the leaves of the tree, while the internal nodes of the tree act as switch boxes and directory-routing points. Each processor node contains a processor, a private cache, and a cache controller. Each switch box contains a message queue, routing logic, a local directory summary for its child leaves, and, when assigned, authoritative directory entries for memory blocks.

A simplified 8-processor example is shown below:

                         S6
                    /          \
                  S4            S5
                /    \        /    \
              S0      S1    S2      S3
             /  \    /  \  /  \    /  \
           P1   P2 P3  P4 P5  P6 P7  P8


In this structure, P1 through P8 are processor nodes, while S0 through S6 are switch nodes. The bottom-level switches group nearby processors together. For example, S0 is the local switch for P1 and P2, while S3 is the local switch for P7 and P8.

This local switch grouping is important because speculative neighbor reads are only allowed within the same local leaf group. For example, if P2 misses on a block that P1 already holds in a shared state, then S0 may detect that local candidate and initiate a speculative fetch. However, `P2` may not speculate from `P8`, even if an express lane makes `P8` faster to reach. This keeps speculation local and bounded.

## Express Lanes

A pure binary tree has a major disadvantage: communication between distant leaves may require traveling up to the root and then back down the opposite side of the tree. For example, without additional links, a message from P1 to P8 would travel:


P1 -> S0 -> S4 -> S6 -> S5 -> S3 -> P8


This creates long traversal paths and can place pressure on upper-level switches near the root.

To reduce long-distance traversal latency, the network adds express lanes between mirrored bottom-level switches. These express lanes do not replace the binary tree. Instead, they act as shortcut links that preserve the tree hierarchy while reducing worst-case path length.

For an 8-processor system, the bottom-level switches are:


S0, S1, S2, S3


The mirror express lanes are:


S0 <-> S3
S1 <-> S2


With these links, a message from `P1` to `P8` can travel:


P1 -> S0 -> S3 -> P8


instead of traveling through the root of the tree.

## Express-Lane Scaling Rule

The express lanes scale according to the number of bottom-level switches. If there are `B` bottom-level switches, each bottom switch is paired with its mirror on the opposite side of the network:


bottom_switch[i] <-> bottom_switch[B - 1 - i]


For an 8-processor system:


Bottom switches: S0 S1 S2 S3

Express lanes:
S0 <-> S3
S1 <-> S2


For a 16-processor system:


Bottom switches: S0 S1 S2 S3 S4 S5 S6 S7

Express lanes:
S0 <-> S7
S1 <-> S6
S2 <-> S5
S3 <-> S4


For a 32-processor system:


Bottom switches: S0 S1 S2 S3 S4 S5 S6 S7 S8 S9 S10 S11 S12 S13 S14 S15

Express lanes:
S0  <-> S15
S1  <-> S14
S2  <-> S13
S3  <-> S12
S4  <-> S11
S5  <-> S10
S6  <-> S9
S7  <-> S8


This rule gives every bottom-level processor group one fast path to the opposite side of the network without making the network fully connected.

## Why the Network Is Not Fully Connected

The goal of the express lanes is not to create a mesh or a fully connected network. A fully connected network would reduce traversal time, but it would also scale poorly because the number of links would grow rapidly as the number of switches increases.

Instead, this project uses a sparse express-lane strategy. Each bottom-level switch receives only one express connection to its mirrored counterpart. This keeps the network simple while still reducing the cost of long-distance communication.

The result is a folded binary-tree style network:

* the binary tree provides the main scalable hierarchy
* the express lanes reduce long-distance traversal
* the local switch groups define the speculation domain
* the home directory still validates correctness

## Role of Express Lanes in Speculation

Express lanes are used for routing messages more efficiently, but they do not expand the set of nodes that are allowed to provide speculative data.

Speculation is local-only. A switch may only initiate speculative fetches from processors under that same local switch. For example:


S0 local group: P1, P2
S1 local group: P3, P4
S2 local group: P5, P6
S3 local group: P7, P8


So P2 may speculate from P1, but not from P8.

The express lanes may still help route validation requests, invalidations, exclusive ownership requests, and authoritative data responses. However, they are not used to perform remote directory snooping for speculative candidates.

This distinction is important:


Local switch directory:
    Finds nearby speculative candidates.

Express lanes:
    Reduce routing distance across the network.

Home directory:
    Provides authoritative validation and coherence ordering.


By separating these roles, the design keeps speculation bounded while still benefiting from shortcut links across the binary-tree network.

# Race Condition Problem

The speculative read path introduces an important correctness problem: the system may speculatively use a neighboring cache block while another processor is trying to modify that same block.

Consider the following situation:

P2 reads address X.
P2 misses locally.
P2's local switch finds that P1 has address X in SHARED state.
P2 receives speculative data from P1.

At the same time:
P5 requests exclusive ownership of address X so it can write to X.

This creates a race between two coherence events:

1. P2's validation request for the speculative copy
2. P5's exclusive/write request that will invalidate old shared copies

If this race is not handled carefully, the system could allow a processor to compute using data that is no longer globally valid.

Why the Neighbor Copy Is Not Enough

A neighboring cache line in SHARED state is not sufficient proof that the data is globally valid. The neighbor only knows its local cache state. It does not know whether the home directory has already started an ownership transfer, whether an invalidation is pending, or whether the block version has changed.

For this reason, the speculative copy is treated only as a fast candidate. The home directory remains the authority.

The home directory knows:

current block version
current sharers
current owner, if any
whether invalidation is pending
whether another node has requested exclusive ownership

Therefore, speculative data cannot commit until the home directory validates it.

Home Directory Serialization

The home directory solves the race condition by serializing all coherence events for each block. For a given address, the home directory defines the official order of events.

For example, if the home processes the validation first:

1. VALIDATION_REQUEST from P2 for address X
2. EXCLUSIVE_REQUEST from P5 for address X

then P2's speculative read is considered valid. The home adds P2 to the sharer list, then later processes P5's exclusive request. When P5 requests ownership, the home sends invalidations to all sharers, including P2.

In this ordering, P2's read is valid because it happened before P5's write in the official coherence order.

However, if the home processes the exclusive request first:

1. EXCLUSIVE_REQUEST from P5 for address X
2. VALIDATION_REQUEST from P2 for address X

then the home marks the block as invalidation-pending. When P2's validation request arrives, the home rejects it. P2 must flush the speculative work and wait for authoritative data.

Validation Rules

A speculative validation request succeeds only if all of the following are true:

the block version matches the home directory version
the source neighbor is still listed as a valid sharer
the block is in a readable shared state
no invalidation is currently pending
no exclusive ownership request has already been serialized first

If these conditions are met, the home sends VALIDATION_SUCCESS.

If any condition fails, the home sends VALIDATION_FAIL.

What Happens After Validation Success

Once validation succeeds, the speculative value becomes a real loaded operand. A later invalidation does not retroactively invalidate computation that already used that validated value.

For example:

Cycle 10: P2 receives speculative data X = 5
Cycle 12: Home validates P2's read of X
Cycle 13: P2 continues computation using X = 5
Cycle 15: P2 receives invalidation for X
Cycle 16: P2 invalidates the cache line for X
Cycle 17: P2 may still continue using the already-loaded value X = 5

The important distinction is:

The loaded operand is valid.
The cache line is no longer valid for future reads.

After invalidation, any future read of that address must miss and request the block again.

What Happens If Validation Fails

If the validation fails, then the speculative data was not safe to use. The processor flushes the speculative load buffer and discards any dependent speculative computation.

The processor must then fall back to the normal directory-coherent path and wait for authoritative data.

P2 receives speculative data
Home rejects validation
P2 flushes speculative state
P2 waits for authoritative data
Invalidation During Pending Speculation

If an invalidation arrives before the speculative load has been validated, the speculative load is squashed. This prevents the processor from committing work based on an uncertain value.

PENDING_VALIDATION + INVALIDATE -> SQUASH
PENDING_VALIDATION + VALIDATION_FAIL -> SQUASH
PENDING_VALIDATION + VALIDATION_SUCCESS -> VALIDATED

Once the value is validated, a later invalidation only invalidates the cache line. It does not destroy the already-validated operand.

VALIDATED + INVALIDATE -> invalidate cache line, keep loaded operand
Summary

The race condition is handled by making the home directory the single serialization point for each cache block. Neighboring caches may provide speculative data quickly, but only the home directory can decide whether that data is globally valid.


## Experiment: Clock-Cycle Savings from Express Lanes

This project compares two network configurations:

1. Baseline binary-tree network
2. Binary-tree network with mirror express lanes

The goal of the experiment is to measure how many clock cycles are saved when messages can use express lanes instead of routing only through the binary-tree hierarchy.

In the baseline binary tree, communication between distant leaves often requires traveling up the tree toward the root and then back down the opposite side. For a system with N processor leaves, the height of the tree is approximately log2(N).

A message traveling from a leaf to the root has a path length of approximately log2(N). A message traveling from one distant leaf to another distant leaf may require approximately 2 × log2(N), because it climbs from the source leaf to the root and then descends from the root to the destination leaf.

For example, in an 8-processor binary tree:

```
                     S6
                /          \
              S4            S5
            /    \        /    \
          S0      S1    S2      S3
         /  \    /  \  /  \    /  \
       P1   P2 P3  P4 P5  P6 P7  P8
```

A message from P1 to P8 in the normal binary tree follows:

P1 → S0 → S4 → S6 → S5 → S3 → P8

This is 6 hops.

With mirror express lanes, the bottom-level switches are connected to their mirrored counterparts:

S0 ↔ S3
S1 ↔ S2

Now the same P1 to P8 path can become:

P1 → S0 → S3 → P8

This is only 3 hops.

Therefore, for this example:

Baseline binary tree path: 6 hops
Express-lane path: 3 hops
Cycles saved: 3 cycles
Path reduction: 50%

## Scaling Behavior

For a binary tree with N processor leaves, the worst-case leaf-to-leaf distance in the baseline network is approximately 2 × log2(N).

With mirror express lanes between bottom-level switches, many cross-network leaf-to-leaf paths are reduced because the message no longer has to travel through the root. A cross-network message can often travel from the source processor to its local bottom switch, across the mirror express lane, and then down to the destination processor. This creates a path length close to 3 hops for mirrored bottom-switch pairs.

The difference becomes more important as N increases.

| Processor Count | Baseline Worst-Case Leaf-to-Leaf Distance | Mirror Express-Lane Distance | Approximate Cycles Saved |
| --------------: | ----------------------------------------: | ---------------------------: | -----------------------: |
|               8 |                                         6 |                            3 |                        3 |
|              16 |                                         8 |                            3 |                        5 |
|              32 |                                        10 |                            3 |                        7 |
|              64 |                                        12 |                            3 |                        9 |

This shows the main advantage of express lanes: the baseline binary-tree distance grows logarithmically with the number of processor nodes, while selected express-lane paths can remain much shorter.

## Validation Delay

In the baseline binary tree, a validation request must travel from the requesting node toward the home directory. If the home directory is far away, this can take approximately log2(N) hops, or more depending on where the home node is located in the tree.

In the express-lane network, validation messages may be routed through shortcut links. This can reduce the validation delay when the home directory lies across the network from the requester.

For example, without express lanes, a validation request may need to travel through the root:

P1 → S0 → S4 → S6 → S5 → S3

With an express lane, the path may become:

P1 → S0 → S3

This reduces the number of switch stages the validation request must traverse.

## Queueing Delay

The simulator also models switch queues. Each switch can only process a limited number of messages per cycle, currently one message per switch per cycle. This means the total delay is not only determined by the number of hops in the network. It also depends on how many messages are waiting in the switch buffers.

The total observed delay can be thought of as:

total delay = path traversal delay + switch queueing delay

This is important because an express-lane path may still experience additional delay if several messages arrive at the same switch at the same time. In other words, shorter paths do not completely eliminate network contention.

However, my hypothesis is that the queueing delay is usually not significantly worse than the base case of traversing the full binary-tree network. Even when express lanes add traffic to bottom-level switches, they also reduce pressure on the upper levels of the tree, especially near the root. Since the root and upper-level switches are natural bottlenecks in a pure binary tree, allowing some traffic to bypass them may reduce total congestion rather than increase it.

Because of this, the express-lane network is expected to improve latency in two ways:

1. It reduces the raw number of hops for cross-network communication.
2. It may reduce queue buildup near the root by spreading traffic across shortcut paths.

The final measured latency should therefore be evaluated using both hop count and queued-cycle delay.

## Expected Results

The expected result is that the express-lane network should show:

* lower average message latency
* lower worst-case traversal latency
* reduced traffic through the root switch
* faster validation responses for cross-network requests
* faster invalidation and ownership-transfer messages

The largest benefit should appear when communication occurs between processor groups on opposite sides of the binary tree.

The smallest benefit should appear when communication is already local, such as between two processors under the same bottom-level switch.

## Summary

The baseline binary tree is scalable, but its long-distance communication cost grows with tree height. In contrast, the mirror express-lane network preserves the binary-tree hierarchy while adding a small number of shortcut links. These links reduce worst-case traversal distance and can lower validation, invalidation, and data-response latency without making the network fully connected.

Although switch queues can add extra delay, the hypothesis is that the express-lane paths will usually remain faster than the baseline binary-tree traversal. Even when queueing occurs, the reduced path length and reduced root-switch pressure should make the express-lane network more efficient for long-distance communication.

