from __future__ import annotations

import uuid
from typing import Any

from livekit_interaction_model_demo.runtime.actions import ActionType


class Mock3DSoundProvider:
    """Produces a sound plan only; no real 3D mixing happens here."""

    def plan(self, *, action: ActionType, text: str, scene_context: dict[str, Any] | None = None) -> dict[str, Any]:
        scene_context = scene_context or {}
        defaults = {
            ActionType.BACKCHANNEL: {"azimuth_deg": -8, "distance_m": 0.85, "gain_db": -7, "ducking": False},
            ActionType.SHORT_REPLY: {"azimuth_deg": 0, "distance_m": 1.0, "gain_db": -2, "ducking": True},
            ActionType.BARGE_IN: {"azimuth_deg": 12, "distance_m": 0.72, "gain_db": 0, "ducking": True},
            ActionType.INTERRUPT_SELF: {"azimuth_deg": 0, "distance_m": 1.0, "gain_db": -24, "ducking": False},
            ActionType.DEFER_BACKGROUND: {"azimuth_deg": 0, "distance_m": 2.0, "gain_db": -18, "ducking": False},
            ActionType.LISTEN: {"azimuth_deg": 0, "distance_m": 1.2, "gain_db": -12, "ducking": False},
        }
        plan = {
            "plan_id": uuid.uuid4().hex[:10],
            "mock": True,
            "action": action.value,
            "text_preview": text[:80],
            "scene": scene_context,
            "spatial": defaults[action],
        }
        if action is ActionType.BARGE_IN:
            plan["priority"] = "high"
            plan["sound"] = {
                "name": "soft_interrupt_chime",
                "asset": "mock://soft_interrupt_chime",
                "gain_db": -10,
                "start_offset_ms": 0,
            }
            plan["mix"] = {"sidechain_user_mic": True, "attack_ms": 80, "release_ms": 320}
        elif action is ActionType.BACKCHANNEL:
            plan["priority"] = "low"
            plan["sound"] = {
                "name": "low_priority_backchannel_presence",
                "asset": "mock://subtle_presence",
                "gain_db": -18,
                "start_offset_ms": 0,
            }
            plan["mix"] = {"sidechain_user_mic": False, "attack_ms": 10, "release_ms": 120}
        else:
            plan["priority"] = "background"
            plan["sound"] = {}
            plan["mix"] = {"sidechain_user_mic": False, "attack_ms": 40, "release_ms": 180}
        return plan
