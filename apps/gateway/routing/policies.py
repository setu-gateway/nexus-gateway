from enum import Enum


class RoutingPolicy(str, Enum):
    """Selectable strategies the router uses to rank healthy candidates (RFC-0005)."""

    LOWEST_LATENCY = "lowest_latency"
    LOWEST_COST = "lowest_cost"
    HIGHEST_AVAILABILITY = "highest_availability"
    USER_PREFERENCE = "user_preference"
    ROUND_ROBIN = "round_robin"
    WEIGHTED = "weighted"
    CAPABILITY_BASED = "capability_based"
