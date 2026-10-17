"""Typed failures used by the KDA experimental evaluation engine."""


class KDAExperimentError(RuntimeError):
    """Base error suitable for concise CLI reporting."""


class ContractError(KDAExperimentError):
    """A task contract or evaluator response is invalid."""


class IntegrityError(KDAExperimentError):
    """An immutable artifact or recorded identity no longer matches."""


class ExecutionError(KDAExperimentError):
    """A child command or execution launcher failed."""

