"""Choose and start the work for one Dreamcatcher instance."""

from dreamcatcher.scheduler.assignments import (
    AgentAssignmentInspectionResult,
    FaultedAgentAssignment,
    RequiredAgentRound,
    compose_assignment_observation,
    compose_initial_round_requirement,
    derive_round_purpose,
    inspect_agent_assignment,
    list_assignment_observations,
    prioritize_required_rounds,
)
from dreamcatcher.scheduler.conversations import (
    IssueConversationCandidate,
    IssueConversationCandidateResult,
    IssueConversationRecoveryCandidate,
    NewIssueConversationRoundCandidate,
)
from dreamcatcher.scheduler.coordinator import AgentWorkScheduler
from dreamcatcher.scheduler.faults import (
    InvalidSchedulerRecordError,
    derive_agent_work_fault,
    read_scheduler_record,
)
from dreamcatcher.scheduler.issues import IssueObservationResult, observe_issues
from dreamcatcher.scheduler.models import (
    DEFAULT_MAX_AGENTS,
    GLOBAL_COOLDOWN_DURATION,
    NO_ROUND_HAS_RUN,
    AgentAssignmentObservation,
    GlobalCooldown,
    IssueConversationObservation,
    IssueFact,
    IssueFactValue,
    IssueObservation,
    SchedulerRecord,
    derive_issue_availability,
)

__all__ = [
    "DEFAULT_MAX_AGENTS",
    "GLOBAL_COOLDOWN_DURATION",
    "NO_ROUND_HAS_RUN",
    "AgentAssignmentInspectionResult",
    "AgentAssignmentObservation",
    "AgentWorkScheduler",
    "FaultedAgentAssignment",
    "GlobalCooldown",
    "InvalidSchedulerRecordError",
    "IssueConversationCandidate",
    "IssueConversationCandidateResult",
    "IssueConversationObservation",
    "IssueConversationRecoveryCandidate",
    "IssueFact",
    "IssueFactValue",
    "IssueObservation",
    "IssueObservationResult",
    "NewIssueConversationRoundCandidate",
    "RequiredAgentRound",
    "SchedulerRecord",
    "compose_assignment_observation",
    "compose_initial_round_requirement",
    "derive_agent_work_fault",
    "derive_issue_availability",
    "derive_round_purpose",
    "inspect_agent_assignment",
    "list_assignment_observations",
    "observe_issues",
    "prioritize_required_rounds",
    "read_scheduler_record",
]
