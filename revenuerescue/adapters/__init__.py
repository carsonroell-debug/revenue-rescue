"""Agent adapters: the abstraction boundary between agent platforms and the
Revenue Rescue audit engine.

Design rule: revenuerescue.audit knows NOTHING about agents. It takes
(site_name, base_url) and returns a report dict. Everything platform-specific
(tool schemas, invocation conventions, response formatting, auth expectations)
lives here, behind the AgentAdapter interface.

Adding a new platform (e.g. Claude Skills, Gemini extensions) means writing one
new adapter module that subclasses AgentAdapter and implements describe() and
invoke(). The engine is never touched.
"""
from abc import ABC, abstractmethod


class AgentAdapter(ABC):
    """Translate one agent platform's invocations into engine calls."""

    #: stable platform identifier, e.g. "muse", "openai-apps"
    platform = "base"

    @abstractmethod
    def describe(self):
        """Return the platform's capability descriptor for this connector:
        tool/function definitions, display name, description, and any
        platform-specific metadata (auth hints, example utterances)."""

    @abstractmethod
    def invoke(self, tool, args):
        """Execute a named tool with platform-shaped args. Returns a plain
        dict; the adapter is responsible for shaping it into the platform's
        expected response format."""

    # --- shared helpers (platform-neutral) ---------------------------------
    @staticmethod
    def summarize(report):
        """One-screen agent-readable summary of an audit report."""
        findings = report.get("findings", [])
        lines = [
            f"Audit of {report.get('site')} ({report.get('base')})",
            f"Pages scanned: {len(report.get('pages', []))}; "
            f"links checked: {len(report.get('link_checks', []))}; "
            f"findings: {len(findings)}",
        ]
        for f in findings[:10]:
            lines.append(f"- {f['finding']}: {f['url']} (on {f['page']})")
        if len(findings) > 10:
            lines.append(f"... and {len(findings) - 10} more findings.")
        if not findings:
            lines.append("No confirmed revenue leaks. All checked links resolved.")
        return "\n".join(lines)
