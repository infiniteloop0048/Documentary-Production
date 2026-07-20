"""Unit tests for shorts script-generation helpers: word-target math and
sentence splitting."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from docu_studio.shorts.shorts_script_gen import (
    ShortsScript,
    generate_shorts_script,
    split_sentences,
    target_word_count,
)
from docu_studio.common.tts_calibration import record_measurement


def _patched_calibration(tmp_path: Path):
    return patch("docu_studio.common.tts_calibration.config_dir", return_value=tmp_path)


class TestTargetWordCount:
    def test_thirty_seconds_at_170_wpm(self) -> None:
        assert target_word_count(30) == round(30 / 60 * 170)  # 85

    def test_fifteen_seconds_minimum(self) -> None:
        assert target_word_count(15) == round(15 / 60 * 170)  # 42 or 43

    def test_sixty_seconds_maximum(self) -> None:
        assert target_word_count(60) == 170

    def test_scales_linearly_with_duration(self) -> None:
        assert target_word_count(60) == target_word_count(30) * 2 or \
            abs(target_word_count(60) - target_word_count(30) * 2) <= 1

    def test_uses_explicit_wpm_override(self) -> None:
        assert target_word_count(30, wpm=120.0) == round(30 / 60 * 120.0)  # 60


class TestSplitSentences:
    def test_splits_on_terminal_punctuation(self) -> None:
        text = "This is one. This is two! Is this three?"
        assert split_sentences(text) == [
            "This is one.", "This is two!", "Is this three?",
        ]

    def test_collapses_internal_whitespace(self) -> None:
        text = "Hello   world.\nSecond   line."
        result = split_sentences(text)
        assert result == ["Hello world.", "Second line."]

    def test_empty_text_returns_empty_list(self) -> None:
        assert split_sentences("") == []
        assert split_sentences("   ") == []

    def test_single_sentence_no_trailing_punctuation(self) -> None:
        assert split_sentences("just one clause") == ["just one clause"]


class TestGenerateShortsScript:
    def test_happy_path_returns_aligned_queries(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = "Fact one is huge. Fact two is bigger. Loop back now."
        llm.break_into_scenes.return_value = [
            {"title": "aerial city night", "narration": "Fact one is huge."},
            {"title": "close-up hands typing", "narration": "Fact two is bigger."},
            {"title": "sunrise timelapse", "narration": "Loop back now."},
        ]

        result = generate_shorts_script("Cities at night", 30, llm)

        assert isinstance(result, ShortsScript)
        assert result.sentences == [
            "Fact one is huge.", "Fact two is bigger.", "Loop back now.",
        ]
        assert result.visual_queries == [
            "aerial city night", "close-up hands typing", "sunrise timelapse",
        ]
        assert len(result.visual_queries) == len(result.sentences)

    def test_malformed_json_response_retries_once_then_falls_back_to_topic(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = "One sentence. Two sentence."
        # First call: wrong count (parse/shape mismatch). Second call: still wrong.
        llm.break_into_scenes.side_effect = [
            [{"title": "only one", "narration": "One sentence."}],  # count mismatch
            RuntimeError("model returned invalid JSON"),             # exception
        ]

        result = generate_shorts_script("Space facts", 30, llm)

        assert result.sentences == ["One sentence.", "Two sentence."]
        assert result.visual_queries == ["Space facts", "Space facts"]
        assert llm.break_into_scenes.call_count == 2

    def test_uses_generate_script_with_target_word_count(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = "Just one sentence here."
        llm.break_into_scenes.return_value = [
            {"title": "topic shot", "narration": "Just one sentence here."},
        ]

        generate_shorts_script("Ocean depths", 15, llm)

        args, kwargs = llm.generate_script.call_args
        # target_words is the 2nd positional/keyword arg to generate_script
        assert kwargs.get("target_words", args[1] if len(args) > 1 else None) == round(15 / 60 * 170)

    def test_empty_script_returns_no_sentences_no_queries(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = ""
        result = generate_shorts_script("Nothing", 30, llm)
        assert result.sentences == []
        assert result.visual_queries == []
        llm.break_into_scenes.assert_not_called()

    def test_uses_default_wpm_when_no_calibration_for_provider(self, tmp_path: Path) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = "Just one sentence here."
        llm.break_into_scenes.return_value = [
            {"title": "topic shot", "narration": "Just one sentence here."},
        ]
        with _patched_calibration(tmp_path):
            generate_shorts_script("Ocean depths", 30, llm, tts_provider="elevenlabs", tts_voice="Rachel")
        args, kwargs = llm.generate_script.call_args
        assert kwargs.get("target_words", args[1] if len(args) > 1 else None) == round(30 / 60 * 170)

    def test_uses_stored_calibration_wpm_for_provider_and_voice(self, tmp_path: Path) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = "Just one sentence here."
        llm.break_into_scenes.return_value = [
            {"title": "topic shot", "narration": "Just one sentence here."},
        ]
        with _patched_calibration(tmp_path):
            # 60 words in 30s -> 120 WPM measured pace for this provider+voice.
            record_measurement("elevenlabs", "Rachel", word_count=60, measured_duration_seconds=30.0)
            generate_shorts_script("Ocean depths", 30, llm, tts_provider="elevenlabs", tts_voice="Rachel")
        args, kwargs = llm.generate_script.call_args
        assert kwargs.get("target_words", args[1] if len(args) > 1 else None) == round(30 / 60 * 120.0)


class TestMusicMoodField:
    def test_parses_music_moods_from_first_entry(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = "Fact one is huge. Fact two is bigger."
        llm.break_into_scenes.return_value = [
            {
                "title": "aerial city night", "narration": "Fact one is huge.",
                "music_moods": ["epic", "cinematic", "dramatic"],
            },
            {"title": "close-up hands typing", "narration": "Fact two is bigger."},
        ]
        result = generate_shorts_script("Cities at night", 30, llm)
        assert result.music_moods == ("epic", "cinematic", "dramatic")

    def test_caps_at_3_tags_and_dedupes(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = "Fact one is huge. Fact two is bigger."
        llm.break_into_scenes.return_value = [
            {
                "title": "aerial city night", "narration": "Fact one is huge.",
                "music_moods": ["epic", "epic", "cinematic", "dramatic", "upbeat"],
            },
            {"title": "close-up hands typing", "narration": "Fact two is bigger."},
        ]
        result = generate_shorts_script("Cities at night", 30, llm)
        assert result.music_moods == ("epic", "cinematic", "dramatic")

    def test_defaults_to_cinematic_when_field_absent(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = "Fact one is huge. Fact two is bigger."
        llm.break_into_scenes.return_value = [
            {"title": "aerial city night", "narration": "Fact one is huge."},
            {"title": "close-up hands typing", "narration": "Fact two is bigger."},
        ]
        result = generate_shorts_script("Cities at night", 30, llm)
        assert result.music_moods == ("cinematic",)

    def test_skips_multi_word_tags_but_keeps_valid_ones(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = "Fact one is huge. Fact two is bigger."
        llm.break_into_scenes.return_value = [
            {
                "title": "aerial city night", "narration": "Fact one is huge.",
                "music_moods": ["very epic indeed", "calm", "not a single word either"],
            },
            {"title": "close-up hands typing", "narration": "Fact two is bigger."},
        ]
        result = generate_shorts_script("Cities at night", 30, llm)
        assert result.music_moods == ("calm",)

    def test_defaults_to_cinematic_when_extraction_fails_entirely(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = "One sentence. Two sentence."
        llm.break_into_scenes.side_effect = RuntimeError("model returned invalid JSON")
        result = generate_shorts_script("Space facts", 30, llm)
        assert result.music_moods == ("cinematic",)

    def test_mood_extraction_does_not_add_extra_llm_calls(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = "One sentence. Two sentence."
        llm.break_into_scenes.side_effect = [
            [{"title": "only one", "narration": "One sentence."}],  # count mismatch -> retry
            RuntimeError("still bad"),
        ]
        generate_shorts_script("Space facts", 30, llm)
        assert llm.break_into_scenes.call_count == 2


class TestGenerateShortsScriptAiImageIndependent:
    def test_populates_image_prompts_aligned_to_sentences(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = "Fact one is huge. Fact two is bigger."
        llm.break_into_scenes.return_value = [
            {
                "title": "aerial city night", "narration": "Fact one is huge.",
                "image_prompt": "Wide establishing shot of a glittering city skyline at night, cinematic lighting.",
                "music_moods": ["epic", "cinematic", "dramatic"],
            },
            {
                "title": "close-up hands typing", "narration": "Fact two is bigger.",
                "image_prompt": "Close-up of hands typing rapidly on a mechanical keyboard, warm desk lamp light.",
            },
        ]

        result = generate_shorts_script(
            "Cities at night", 30, llm, footage_source="ai_image", story_continuity=False,
        )

        assert len(result.image_prompts) == 2
        assert "glittering city skyline" in result.image_prompts[0]
        assert "hands typing" in result.image_prompts[1]
        # visual_queries (stock fallback) still populated regardless of mode:
        assert result.visual_queries == ["aerial city night", "close-up hands typing"]

    def test_does_not_call_style_guide_generation_when_independent(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = "One sentence. Two sentence."
        llm.break_into_scenes.return_value = [
            {"title": "a", "narration": "One sentence.", "image_prompt": "prompt one"},
            {"title": "b", "narration": "Two sentence.", "image_prompt": "prompt two"},
        ]

        generate_shorts_script("Topic", 30, llm, footage_source="ai_image", story_continuity=False)

        # generate_script called exactly once (for the main narration only —
        # no extra style-guide call):
        assert llm.generate_script.call_count == 1

    def test_video_mode_leaves_image_prompts_empty(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = "One sentence. Two sentence."
        llm.break_into_scenes.return_value = [
            {"title": "a", "narration": "One sentence."},
            {"title": "b", "narration": "Two sentence."},
        ]

        result = generate_shorts_script("Topic", 30, llm, footage_source="video")

        assert result.image_prompts == ()


class TestGenerateShortsScriptAiImageStoryContinuity:
    def test_style_guide_call_happens_before_per_sentence_call(self) -> None:
        llm = MagicMock()
        llm.generate_script.side_effect = [
            "Fact one is huge. Fact two is bigger.",  # main narration call
            "Cinematic photography style, warm palette. A lone astronaut in a weathered white suit.",  # style-guide call
        ]
        llm.break_into_scenes.return_value = [
            {
                "title": "astronaut walking", "narration": "Fact one is huge.",
                "image_prompt": "Cinematic photography, warm palette, lone astronaut in weathered white suit walking on dunes.",
                "music_moods": ["epic", "cinematic", "dramatic"],
            },
            {
                "title": "astronaut looking up", "narration": "Fact two is bigger.",
                "image_prompt": "Cinematic photography, warm palette, same astronaut looking up at a huge red planet.",
            },
        ]

        result = generate_shorts_script(
            "A lone astronaut", 30, llm, footage_source="ai_image", story_continuity=True,
        )

        assert llm.generate_script.call_count == 2
        assert len(result.image_prompts) == 2
        assert "astronaut" in result.image_prompts[0]
        assert "astronaut" in result.image_prompts[1]

    def test_style_guide_failure_falls_back_to_independent_prompts(self) -> None:
        llm = MagicMock()
        llm.generate_script.side_effect = [
            "One sentence. Two sentence.",
            RuntimeError("style guide call failed"),
        ]
        llm.break_into_scenes.return_value = [
            {"title": "a", "narration": "One sentence.", "image_prompt": "prompt one"},
            {"title": "b", "narration": "Two sentence.", "image_prompt": "prompt two"},
        ]

        result = generate_shorts_script(
            "Topic", 30, llm, footage_source="ai_image", story_continuity=True,
        )

        assert len(result.image_prompts) == 2

    def test_image_prompt_extraction_failure_falls_back_to_visual_queries(self) -> None:
        llm = MagicMock()
        llm.generate_script.return_value = "One sentence. Two sentence."
        # Both scene-extraction attempts are missing image_prompt entirely:
        llm.break_into_scenes.return_value = [
            {"title": "query one", "narration": "One sentence."},
            {"title": "query two", "narration": "Two sentence."},
        ]

        result = generate_shorts_script(
            "Topic", 30, llm, footage_source="ai_image", story_continuity=False,
        )

        assert result.image_prompts == ("query one", "query two")
