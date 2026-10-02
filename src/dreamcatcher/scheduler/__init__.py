"""Choose and start the work for one Dreamcatcher instance."""

from dreamcatcher.scheduler.coordinator import AgentWorkScheduler
from dreamcatcher.scheduler.faults import (
    InvalidSchedulerRecordError,
    derive_agent_work_fault,
    read_scheduler_record,
)
from dreamcatcher.scheduler.models import DEFAULT_MAX_AGENTS, SchedulerRecord

__all__ = [
    "DEFAULT_MAX_AGENTS",
    "AgentWorkScheduler",
    "InvalidSchedulerRecordError",
    "SchedulerRecord",
    "derive_agent_work_fault",
    "read_scheduler_record",
]
