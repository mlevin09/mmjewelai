"""Application boundary for untrusted natural-language understanding."""

from typing import Literal, Protocol

from jewelai_parser import ParserCandidate


class TextUnderstandingProvider(Protocol):
    def understand(self, message: str, locale: Literal["en", "ru"]) -> ParserCandidate: ...
