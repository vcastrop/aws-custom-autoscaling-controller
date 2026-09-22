import json
import time
from pathlib import Path


class ControllerState:
    """
    Persistent state used by the elasticity controller.

    The state survives between controller executions and is used
    primarily to enforce the cooldown period after scaling actions.
    """

    def __init__(self, config, state_file=None):
        self.config = config

        if state_file is None:
            base_dir = Path(__file__).resolve().parent.parent
            state_file = base_dir / "controller_state.json"

        self.state_file = Path(state_file)

    # ---------------------------------------------------------
    # DEFAULT STATE
    # ---------------------------------------------------------

    def default_state(self):
        return {
            "last_scaling_time": None,
            "last_scaling_action": None,
        }

    # ---------------------------------------------------------
    # LOAD
    # ---------------------------------------------------------

    def load(self):
        """
        Load persistent controller state.

        If the file does not exist or cannot be parsed,
        return a safe default state.
        """

        if not self.state_file.exists():
            return self.default_state()

        try:
            with self.state_file.open("r", encoding="utf-8") as file:
                state = json.load(file)

            if not isinstance(state, dict):
                return self.default_state()

            return {
                "last_scaling_time": state.get("last_scaling_time"),
                "last_scaling_action": state.get("last_scaling_action"),
            }

        except (OSError, json.JSONDecodeError):
            return self.default_state()

    # ---------------------------------------------------------
    # SAVE
    # ---------------------------------------------------------

    def save(self, state):
        """
        Persist controller state atomically.
        """

        temporary_file = self.state_file.with_suffix(".tmp")

        with temporary_file.open("w", encoding="utf-8") as file:
            json.dump(state, file, indent=2)

        temporary_file.replace(self.state_file)

    # ---------------------------------------------------------
    # COOLDOWN
    # ---------------------------------------------------------

    def cooldown_status(self):
        """
        Return whether cooldown is active and how many seconds remain.
        """

        state = self.load()

        last_scaling_time = state.get("last_scaling_time")

        if last_scaling_time is None:
            return {
                "active": False,
                "remaining_seconds": 0,
            }

        cooldown_seconds = self.config["timing"]["cooldown_seconds"]

        elapsed = time.time() - float(last_scaling_time)
        remaining = cooldown_seconds - elapsed

        if remaining > 0:
            return {
                "active": True,
                "remaining_seconds": int(remaining),
            }

        return {
            "active": False,
            "remaining_seconds": 0,
        }

    # ---------------------------------------------------------
    # RECORD SUCCESSFUL SCALING
    # ---------------------------------------------------------

    def record_scaling_action(self, action):
        """
        Record a successfully completed scaling action.

        Cooldown begins only after the actuator reports that the
        scaling action completed successfully.
        """

        state = {
            "last_scaling_time": time.time(),
            "last_scaling_action": action,
        }

        self.save(state)