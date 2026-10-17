"""Choose and start the work for one dreamcatcher instance."""

from dreamcatcher.scheduler.faults import (
    InvalidSchedulerRecordError,
    derive_agent_work_fault,
    read_scheduler_record,
)
from dreamcatcher.scheduler.inspection import SchedulingContext
from dreamcatcher.scheduler.models import DEFAULT_MAX_AGENTS, SchedulerRecord
from dreamcatcher.scheduler.tick import Scheduler

__all__ = [
    "DEFAULT_MAX_AGENTS",
    "InvalidSchedulerRecordError",
    "Scheduler",
    "SchedulerRecord",
    "SchedulingContext",
    "derive_agent_work_fault",
    "read_scheduler_record",
]
