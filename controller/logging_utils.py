import json
from datetime import datetime, timezone
from pathlib import Path


class DecisionLogger:
    """
    Stores one structured JSON record for every controller cycle.

    The JSONL format allows the experiment to be analyzed later
    without depending only on screenshots or console output.
    """

    def __init__(self, log_file=None):

        if log_file is None:
            base_dir = Path(__file__).resolve().parent.parent
            log_directory = base_dir / "logs"
            log_directory.mkdir(parents=True, exist_ok=True)

            log_file = log_directory / "decisions.jsonl"

        self.log_file = Path(log_file)

        self.log_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

    def log_cycle(
        self,
        observation,
        decision,
        cooldown_status,
        action_result=None,
    ):
        """
        Record a complete controller cycle.
        """

        record = {
            "logged_at": datetime.now(
                timezone.utc
            ).isoformat(),

            "observation": {
                "timestamp": observation["timestamp"],

                "capacity": observation["capacity"],

                "metrics": {
                    "average_cpu": observation[
                        "metrics"
                    ]["cpu"]["average"],

                    "maximum_cpu": observation[
                        "metrics"
                    ]["cpu"]["maximum"],

                    "per_instance_cpu": observation[
                        "metrics"
                    ]["cpu"]["per_instance"],

                    "request_count": observation[
                        "metrics"
                    ]["request_count"],
                },
            },

            "controller_state": {
                "cooldown_active": cooldown_status[
                    "active"
                ],
                "cooldown_remaining_seconds": (
                    cooldown_status[
                        "remaining_seconds"
                    ]
                ),
            },

            "decision": {
                "action": decision.action,
                "reason": decision.reason,
                "current_capacity": (
                    decision.current_capacity
                ),
                "target_capacity": (
                    decision.target_capacity
                ),
            },

            "action_result": action_result,
        }

        with self.log_file.open(
            "a",
            encoding="utf-8",
        ) as file:

            file.write(
                json.dumps(
                    record,
                    default=str,
                )
                + "\n"
            )

        return record