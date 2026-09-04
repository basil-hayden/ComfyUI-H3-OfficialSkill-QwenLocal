from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
from .managed_qwen import H3OfficialSkillQwenLocal

NODE_CLASS_MAPPINGS["H3OfficialSkillQwenLocal"] = H3OfficialSkillQwenLocal
NODE_DISPLAY_NAME_MAPPINGS["H3OfficialSkillQwenLocal"] = "H3 官方 Skill · Qwen 本地自动优化"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
