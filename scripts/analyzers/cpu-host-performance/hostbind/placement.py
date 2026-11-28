"""NUMA policy for verified A3 workload owners with no hardware CPU affinity."""

EXPLICIT = 'EXPLICIT_AFFINITY'
A3_POLICY = 'A3_BALANCED_POLICY'


def supports_balancing(product):
    return product.get('generation') == 'A3' and product.get('status') == 'identified'


def node_order(nodes, device_counts):
    """One placement per active NPU. Sparse node numbers are ordered numerically."""
    return sorted(nodes, key=lambda node: (device_counts.get(node, 0), node))
