from __future__ import annotations


class TextSegmenter:
    """Token segmenter for realtime LLM output.

    Visible text is buffered until sentence punctuation or a maximum character
    count is reached. Content inside <think>...</think> is dropped, including
    when tags span token boundaries.
    """

    def __init__(self, *, max_chars: int = 120):
        self.max_chars = max_chars
        self._visible = ""
        self._scan = ""
        self._hidden = False

    def feed(self, token: str) -> list[str]:
        visible = self._filter_think(token)
        if not visible:
            return []
        self._visible += visible
        return self._drain_segments(force=False)

    def flush(self) -> list[str]:
        # Unterminated think content stays hidden by design.
        self._scan = ""
        return self._drain_segments(force=True)

    def reset(self) -> None:
        self._visible = ""
        self._scan = ""
        self._hidden = False

    def _filter_think(self, token: str) -> str:
        self._scan += token
        out: list[str] = []
        while self._scan:
            if self._hidden:
                end = self._scan.find("</think>")
                if end < 0:
                    # Keep only a suffix long enough to complete an end tag.
                    self._scan = self._scan[-7:]
                    return "".join(out)
                self._scan = self._scan[end + len("</think>") :]
                self._hidden = False
                continue

            start = self._scan.find("<think>")
            if start >= 0:
                out.append(self._scan[:start])
                self._scan = self._scan[start + len("<think>") :]
                self._hidden = True
                continue

            # If the buffer ends with a possible partial opening tag, retain it.
            keep = self._partial_prefix_len(self._scan, "<think>")
            if keep:
                out.append(self._scan[:-keep])
                self._scan = self._scan[-keep:]
                return "".join(out)
            out.append(self._scan)
            self._scan = ""
        return "".join(out)

    def _drain_segments(self, *, force: bool) -> list[str]:
        segments: list[str] = []
        while self._visible:
            cut = self._punctuation_cut(self._visible)
            if cut is None and len(self._visible) >= self.max_chars:
                cut = self.max_chars
            if cut is None:
                break
            segment = self._visible[:cut]
            segments.append(segment)
            self._visible = self._visible[cut:]
        if force and self._visible:
            segments.append(self._visible)
            self._visible = ""
        return segments

    @staticmethod
    def _punctuation_cut(text: str) -> int | None:
        indexes = [idx for mark in (".", "!", "?", "\n") if (idx := text.find(mark)) >= 0]
        if not indexes:
            return None
        return min(indexes) + 1

    @staticmethod
    def _partial_prefix_len(text: str, marker: str) -> int:
        max_len = min(len(text), len(marker) - 1)
        for size in range(max_len, 0, -1):
            if marker.startswith(text[-size:]):
                return size
        return 0
