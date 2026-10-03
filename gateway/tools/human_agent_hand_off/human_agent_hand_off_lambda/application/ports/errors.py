"""Errors that publisher adapters raise; part of the port contract.

Adapters wrap SDK exceptions in these (``raise ... from exc``) so the use case
can react to failures without importing any infrastructure code. Their
messages are for logs only and are never shown to the agent.
"""


class PublishError(Exception):
    """The hand-off couldn't be published."""
