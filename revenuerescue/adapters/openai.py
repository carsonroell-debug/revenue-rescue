"""OpenAI-shaped adapter generated from Revenue Rescue's canonical tools.

This module demonstrates portability only; the product logic remains in the
shared engine/jobs/monitoring layers.
"""
from . import AgentAdapter
from ..contracts import TOOLS
from .muse import MuseAdapter


class OpenAIAdapter(AgentAdapter):
    platform = "openai-apps"

    FUNCTIONS = [
        {
            "name": item["name"],
            "description": item["description"],
            "parameters": item["input_schema"],
            "strict": True,
        }
        for item in TOOLS
    ]

    def describe(self):
        return {"platform": self.platform, "functions": self.FUNCTIONS}

    def invoke(self, tool, args):
        return MuseAdapter().invoke(tool, args)
