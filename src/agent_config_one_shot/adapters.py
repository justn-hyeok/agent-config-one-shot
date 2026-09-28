"""Native discovery paths; no credentials, personal policies, or model defaults."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Adapter:
    id: str
    executables: tuple[str, ...]
    skills: str
    files: tuple[str, ...] = ()
    authored: tuple[str, ...] = ()
    reads_shared: bool = False
    custom_skills_config: str | None = None


ADAPTERS = {
    item.id: item for item in (
        Adapter("codex", ("codex",), ".codex/skills",
                (".codex/config.toml", ".codex/hooks.json"),
                (".codex/AGENTS.md", ".codex/agent-guides", ".codex/agents", ".codex/hooks"), True),
        Adapter("claude", ("claude",), ".claude/skills",
                (".claude/settings.json",), (".claude/CLAUDE.md",)),
        Adapter("cursor-cli", ("cursor-agent", "agent"), ".cursor/skills",
                (".cursor/cli-config.json", ".cursor/mcp.json", ".cursor/hooks.json"),
                (".cursor/rules",), True),
        Adapter("copilot", ("copilot",), ".copilot/skills",
                (".copilot/settings.json", ".copilot/mcp-config.json"),
                (".copilot/copilot-instructions.md", ".copilot/instructions", ".copilot/agents", ".copilot/hooks"), True),
        Adapter("amp", ("amp",), ".config/amp/skills",
                (".config/amp/settings.json",), (".config/amp/AGENTS.md",), True),
        Adapter("cline", ("cline",), ".cline/skills",
                (".cline/global-settings.json", ".cline/data/settings/cline_mcp_settings.json"),
                (".cline/rules", ".cline/hooks"), True),
        Adapter("opencode", ("opencode",), ".config/opencode/skills",
                (".config/opencode/opencode.json", ".config/opencode/tui.json"),
                (".config/opencode/AGENTS.md", ".config/opencode/agent", ".config/opencode/commands", ".config/opencode/plugins")),
        Adapter("devin", ("devin",), ".config/devin/skills",
                (".config/devin/config.json",)),
        Adapter("omp", ("omp",), ".omp/agent/skills",
                (".omp/agent/config.yml", ".omp/agent/models.yml", ".omp/agent/mcp.json", ".omp/agent/lsp.json"),
                (".omp/agent/AGENTS.md", ".omp/agent/RULES.md", ".omp/agent/extensions")),
        Adapter("gjc", ("gjc",), ".gjc/agent/skills",
                (".gjc/agent/config.yml", ".gjc/agent/models.yml", ".gjc/agent/mcp.json"),
                custom_skills_config=".gjc/agent/config.yml"),
        Adapter("command-code", ("command-code",), ".commandcode/skills",
                (".commandcode/config.json", ".commandcode/settings.json")),
    )
}
