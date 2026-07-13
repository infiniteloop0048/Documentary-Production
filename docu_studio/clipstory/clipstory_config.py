"""Config dataclasses for Clip Story: one ClipSpec per uploaded video clip, one
ClipStoryConfig for the whole project. Validated at construction time — these are
built at the Bridge boundary from user/GUI input, not mutated afterward except to
fill in generated narration text (see clipstory_script_gen.prepare_narration_review)."""
from __future__ import annotations

from dataclasses import dataclass

_VALID_OUTPUT_RESOLUTIONS = ("16:9", "9:16")


@dataclass
class ClipSpec:
    path: str
    trim_in: float
    trim_out: float
    script_text: str = ""
    use_llm_generation: bool = False

    def __post_init__(self) -> None:
        if self.trim_in < 0:
            raise ValueError("trim_in must be non-negative")
        if self.trim_out <= self.trim_in:
            raise ValueError("trim_out must be greater than trim_in")
        if self.use_llm_generation and self.script_text:
            raise ValueError("a clip cannot both have script_text and use_llm_generation set")
        if not self.use_llm_generation and not self.script_text:
            raise ValueError("a clip must have either script_text or use_llm_generation set")

    @property
    def duration_estimate(self) -> float:
        """Simple trim_out - trim_in arithmetic — a sizing estimate only, used
        before any physical trim exists (Layer 1). The render step measures the
        real trimmed file's duration instead (see clipstory_assembly)."""
        return self.trim_out - self.trim_in


@dataclass
class ClipStoryConfig:
    topic: str
    clips: list[ClipSpec]
    output_resolution: str = "16:9"
    tts_provider: str = ""
    tts_voice: str = ""

    def __post_init__(self) -> None:
        if not self.clips:
            raise ValueError("ClipStoryConfig requires at least one clip")
        if self.output_resolution not in _VALID_OUTPUT_RESOLUTIONS:
            raise ValueError(
                f"output_resolution must be one of {_VALID_OUTPUT_RESOLUTIONS}, "
                f"got {self.output_resolution!r}"
            )
