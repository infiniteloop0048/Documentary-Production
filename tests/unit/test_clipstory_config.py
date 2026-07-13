"""Unit tests for clipstory_config: ClipSpec / ClipStoryConfig validation."""
from __future__ import annotations

import pytest

from docu_studio.clipstory.clipstory_config import ClipSpec, ClipStoryConfig


class TestClipSpec:
    def test_valid_user_written_clip(self) -> None:
        clip = ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=10.0, script_text="Hello there.")
        assert clip.duration_estimate == 10.0

    def test_valid_llm_flagged_clip(self) -> None:
        clip = ClipSpec(path="/a.mp4", trim_in=2.0, trim_out=12.5, use_llm_generation=True)
        assert clip.duration_estimate == 10.5

    def test_negative_trim_in_raises(self) -> None:
        with pytest.raises(ValueError, match="trim_in"):
            ClipSpec(path="/a.mp4", trim_in=-1.0, trim_out=10.0, script_text="x")

    def test_trim_out_not_greater_than_trim_in_raises(self) -> None:
        with pytest.raises(ValueError, match="trim_out"):
            ClipSpec(path="/a.mp4", trim_in=5.0, trim_out=5.0, script_text="x")

    def test_trim_out_less_than_trim_in_raises(self) -> None:
        with pytest.raises(ValueError, match="trim_out"):
            ClipSpec(path="/a.mp4", trim_in=5.0, trim_out=2.0, script_text="x")

    def test_both_script_text_and_llm_flag_raises(self) -> None:
        with pytest.raises(ValueError, match="cannot both"):
            ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=10.0, script_text="x", use_llm_generation=True)

    def test_neither_script_text_nor_llm_flag_raises(self) -> None:
        with pytest.raises(ValueError, match="either"):
            ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=10.0)


class TestClipStoryConfig:
    def test_valid_config(self) -> None:
        clips = [ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=10.0, script_text="Hi.")]
        config = ClipStoryConfig(topic="Test", clips=clips)
        assert config.output_resolution == "16:9"

    def test_empty_clip_list_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one clip"):
            ClipStoryConfig(topic="Test", clips=[])

    def test_invalid_output_resolution_raises(self) -> None:
        clips = [ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=10.0, script_text="Hi.")]
        with pytest.raises(ValueError, match="output_resolution"):
            ClipStoryConfig(topic="Test", clips=clips, output_resolution="4:3")

    def test_9_16_output_resolution_accepted(self) -> None:
        clips = [ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=10.0, script_text="Hi.")]
        config = ClipStoryConfig(topic="Test", clips=clips, output_resolution="9:16")
        assert config.output_resolution == "9:16"


class TestClipStoryConfigPhase2Fields:
    def test_defaults_match_phase1_behavior(self) -> None:
        clips = [ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=10.0, script_text="Hi.")]
        config = ClipStoryConfig(topic="Test", clips=clips)
        assert config.transition == "cut"
        assert config.captions is False
        assert config.music_enabled is False
        assert config.music_provider == "jamendo"
        assert config.music_folder == ""
        assert config.jamendo_client_id == ""

    def test_crossfade_transition_accepted(self) -> None:
        clips = [ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=10.0, script_text="Hi.")]
        config = ClipStoryConfig(topic="Test", clips=clips, transition="crossfade")
        assert config.transition == "crossfade"

    def test_invalid_transition_raises(self) -> None:
        clips = [ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=10.0, script_text="Hi.")]
        with pytest.raises(ValueError, match="transition"):
            ClipStoryConfig(topic="Test", clips=clips, transition="wipe")

    def test_local_folder_music_provider_accepted(self) -> None:
        clips = [ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=10.0, script_text="Hi.")]
        config = ClipStoryConfig(topic="Test", clips=clips, music_provider="local_folder")
        assert config.music_provider == "local_folder"

    def test_invalid_music_provider_raises(self) -> None:
        clips = [ClipSpec(path="/a.mp4", trim_in=0.0, trim_out=10.0, script_text="Hi.")]
        with pytest.raises(ValueError, match="music_provider"):
            ClipStoryConfig(topic="Test", clips=clips, music_provider="spotify")
