"""
Parallel analysis agents. Each agent receives a slice of repo context
and produces a section of the final report.
"""

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Awaitable

from openrouter import complete


class Status(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


@dataclass
class AgentResult:
    agent_name: str
    status: Status = Status.PENDING
    progress: str = ""
    output: str = ""


SYSTEM_PROMPT = (
    "You are an expert software architect analyzing a codebase. "
    "Produce clear, detailed technical documentation in Markdown. "
    "Use Mermaid diagram syntax (```mermaid) where requested. "
    "Be thorough but concise. No pleasantries."
)


async def analyze_architecture(context: str, on_progress: Callable) -> str:
    await on_progress("Analyzing overall architecture...")
    return await complete(
        system=SYSTEM_PROMPT,
        prompt=(
            "Given the following repository file tree and key file contents, write an "
            "'Architecture Overview' section. Include:\n"
            "1. High-level system description (purpose, tech stack)\n"
            "2. A Mermaid block diagram showing major components and their relationships\n"
            "3. Entry points and execution flow\n"
            "4. Key design patterns identified\n\n"
            f"Repository context:\n```\n{context[:12000]}\n```"
        ),
        max_tokens=4096,
    )


async def analyze_data_structures(context: str, on_progress: Callable) -> str:
    await on_progress("Mapping data structures and schemas...")
    return await complete(
        system=SYSTEM_PROMPT,
        prompt=(
            "Given the following repository file tree and key file contents, write a "
            "'Data Structures & Schemas' section. Include:\n"
            "1. All major data models/classes/types with their fields\n"
            "2. A Mermaid class diagram showing relationships between models\n"
            "3. Database schemas if present (as Mermaid ER diagram)\n"
            "4. Key enums, constants, and configuration structures\n\n"
            f"Repository context:\n```\n{context[:12000]}\n```"
        ),
        max_tokens=4096,
    )


async def analyze_apis(context: str, on_progress: Callable) -> str:
    await on_progress("Documenting APIs and interfaces...")
    return await complete(
        system=SYSTEM_PROMPT,
        prompt=(
            "Given the following repository file tree and key file contents, write an "
            "'APIs & Interfaces' section. Include:\n"
            "1. All HTTP/REST/GraphQL endpoints with methods, paths, parameters\n"
            "2. Internal module interfaces and public functions\n"
            "3. A Mermaid sequence diagram for the most important user flow\n"
            "4. Authentication/authorization mechanisms\n"
            "5. External service integrations\n\n"
            f"Repository context:\n```\n{context[:12000]}\n```"
        ),
        max_tokens=4096,
    )


async def analyze_dependencies(context: str, on_progress: Callable) -> str:
    await on_progress("Analyzing dependencies and build system...")
    return await complete(
        system=SYSTEM_PROMPT,
        prompt=(
            "Given the following repository file tree and key file contents, write a "
            "'Dependencies & Build System' section. Include:\n"
            "1. All direct dependencies with their purpose\n"
            "2. Build/bundling tools and configuration\n"
            "3. A Mermaid flowchart of the build/deploy pipeline\n"
            "4. Development vs production dependencies\n"
            "5. Environment requirements\n\n"
            f"Repository context:\n```\n{context[:12000]}\n```"
        ),
        max_tokens=4096,
    )


async def analyze_testing(context: str, on_progress: Callable) -> str:
    await on_progress("Reviewing testing and quality...")
    return await complete(
        system=SYSTEM_PROMPT,
        prompt=(
            "Given the following repository file tree and key file contents, write a "
            "'Testing & Quality' section. Include:\n"
            "1. Test framework and tooling\n"
            "2. Test coverage areas and strategies\n"
            "3. CI/CD pipeline if present\n"
            "4. Code quality tools (linters, formatters, type checkers)\n"
            "5. Notable gaps in testing\n\n"
            f"Repository context:\n```\n{context[:12000]}\n```"
        ),
        max_tokens=4096,
    )


async def write_summary(sections: dict[str, str], on_progress: Callable) -> str:
    await on_progress("Writing executive summary...")
    combined = "\n\n---\n\n".join(
        f"## {name}\n{content}" for name, content in sections.items()
    )
    return await complete(
        system=SYSTEM_PROMPT,
        prompt=(
            "Given the following analysis sections of a software repository, write a concise "
            "'Executive Summary' (max 300 words) that captures:\n"
            "1. What the system does\n"
            "2. Key technologies\n"
            "3. Architecture highlights\n"
            "4. Notable strengths and concerns\n\n"
            f"Sections:\n{combined[:14000]}"
        ),
        max_tokens=1500,
    )


# Registry: name -> (function, display_label)
AGENTS: dict[str, tuple] = {
    "architecture": (analyze_architecture, "Architecture Overview"),
    "data_structures": (analyze_data_structures, "Data Structures & Schemas"),
    "apis": (analyze_apis, "APIs & Interfaces"),
    "dependencies": (analyze_dependencies, "Dependencies & Build"),
    "testing": (analyze_testing, "Testing & Quality"),
}
