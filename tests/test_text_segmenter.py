from app.realtime.text_segmenter import TextSegmenter


def test_text_segmenter_segments_on_punctuation():
    segmenter = TextSegmenter(max_chars=80)

    assert segmenter.feed("Hello") == []
    assert segmenter.feed(" world.") == ["Hello world."]
    assert segmenter.flush() == []


def test_text_segmenter_segments_on_max_chars():
    segmenter = TextSegmenter(max_chars=10)

    assert segmenter.feed("12345") == []
    assert segmenter.feed("67890") == ["1234567890"]


def test_text_segmenter_hides_think_tags_across_tokens():
    segmenter = TextSegmenter(max_chars=80)

    assert segmenter.feed("Visible <think>secret") == []
    assert segmenter.feed(" hidden</think> text.") == ["Visible  text."]
    assert segmenter.flush() == []


def test_text_segmenter_flushes_remaining_visible_text():
    segmenter = TextSegmenter(max_chars=80)

    assert segmenter.feed("Trailing text") == []
    assert segmenter.flush() == ["Trailing text"]
