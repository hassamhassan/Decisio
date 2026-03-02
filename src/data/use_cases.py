"""
Decisio — Use Case Test Scenarios (§12)

Four use cases from the draft, expressed as testable scenarios
with expected behaviors and validation criteria.
"""

from __future__ import annotations

USE_CASES = [
    {
        "id": "UC-01",
        "title": "Manufacturing — Machine Stops Without Clear Alarm",
        "sector": "manufacturing",
        "report": (
            "Production machine on Line 3 stopped suddenly. No visible alarms, "
            "no error codes on the HMI. The machine was running normally "
            "15 minutes ago. There was a shift change 2 hours before."
        ),
        "expected_behaviors": [
            "System asks technical questions first (trigger condition, alarms)",
            "System asks process questions early (shift change, handover)",
            "Process failure is detected as suspected root cause",
            "If first-line fails, escalation is triggered",
            "Expert decision logic is captured for future use",
        ],
        "expected_root_cause_category": "process",
        "expected_severity": "high",
        "key_questions_to_include": [
            "Was there a complete shift handover before this incident?",
            "Were any manual steps or configuration changes made recently?",
        ],
    },
    {
        "id": "UC-02",
        "title": "Data Center — Cooling System Partial Failure",
        "sector": "data_center",
        "report": (
            "Cooling support system in Server Room B has a partial failure. "
            "Temperatures are rising. Redundant unit is running but at 90% capacity. "
            "Current room temperature is 28°C, threshold is 32°C. "
            "Estimated time to critical: 45 minutes."
        ),
        "expected_behaviors": [
            "System detects conflicting signals (partial failure + redundancy)",
            "Strict safety constraints applied (temperature threshold)",
            "Blocks risky 'continue running' decisions",
            "Requires immediate escalation",
            "Recommends controlled service removal path",
        ],
        "expected_root_cause_category": "technical",
        "expected_severity": "critical",
        "expected_escalation": True,
        "key_questions_to_include": [
            "Is the redundant cooling unit showing any degradation?",
            "Are all temperature sensors reading correctly?",
        ],
    },
    {
        "id": "UC-03",
        "title": "Logistics — Sorting System Partial Stop Under Pressure",
        "sector": "logistics",
        "report": (
            "Sorting system in Warehouse Zone C has partially stopped. "
            "20% of conveyor lanes are down. Peak shipping window starts in 1 hour. "
            "No mechanical alarms. The night shift operator set the system up this morning."
        ),
        "expected_behaviors": [
            "System uncovers process failure (handover gap)",
            "Corrects the decision procedurally without technical intervention",
            "Documents it to prevent recurrence",
            "No unnecessary escalation if process fix works",
        ],
        "expected_root_cause_category": "process",
        "expected_severity": "medium",
        "key_questions_to_include": [
            "Was the morning setup procedure completed fully?",
            "Were all conveyor zones activated during startup?",
        ],
    },
    {
        "id": "UC-04",
        "title": "Hospital — Non-Clinical Imaging Device Stops",
        "sector": "hospital",
        "report": (
            "MRI imaging device in Radiology Room 2 has stopped mid-scan. "
            "Patient was safely removed. No error messages on console. "
            "The device had scheduled maintenance last week."
        ),
        "expected_behaviors": [
            "Tighter safety and permission constraints due to environment",
            "Pulls anonymized patterns if available",
            "Recommends early OEM escalation",
            "Prevents unsafe restart attempts",
            "Safety constraints mention patient environment",
        ],
        "expected_root_cause_category": "technical",
        "expected_severity": "high",
        "expected_escalation": True,
        "key_questions_to_include": [
            "Was the recent maintenance documented and signed off?",
            "Are there any environmental controls (helium levels, power supply)?",
        ],
    },
]


def get_use_case(use_case_id: str) -> dict | None:
    """Get a use case by ID (e.g., 'UC-01')."""
    for uc in USE_CASES:
        if uc["id"] == use_case_id:
            return uc
    return None


def get_test_reports() -> list[dict]:
    """Get all use cases formatted as test inputs."""
    return [
        {
            "id": uc["id"],
            "title": uc["title"],
            "report": uc["report"],
            "expected_severity": uc.get("expected_severity", "medium"),
            "expected_root_cause": uc.get("expected_root_cause_category", ""),
            "expected_escalation": uc.get("expected_escalation", False),
        }
        for uc in USE_CASES
    ]
