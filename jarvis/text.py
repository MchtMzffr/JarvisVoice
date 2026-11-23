import re


def clean_spoken(text: str) -> str:
    text = re.sub(r"```.*?```", "Kod ayrıntıları ekranda.", text, flags=re.S)
    text = re.sub(r"\[([^\]]+)\]\(https?://[^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\[\d+\]", "", text)
    text = re.sub(r"[*_#`]|\\\(|\\\)|\\\[|\\\]", "", text)
    return re.sub(r"\s+", " ", text).strip()


class SentenceBuffer:
    def __init__(self, max_chars=180):
        self.pending = ""
        self.max_chars = max_chars

    def push(self, text: str, final=False):
        self.pending += text
        result = []
        while self.pending:
            # Require whitespace/end after punctuation; 3.5 remains intact.
            # A stream chunk ending in '3.' may be followed by '5'; wait for
            # actual whitespace, unless the stream has ended.
            boundary = r"[.!?](?=\s|$)" if final else r"[.!?](?=\s)"
            match = re.search(boundary, self.pending)
            cut = match.end() if match else 0
            if cut and self.pending[:cut].strip().lower() in {"dr.", "prof.", "sn.", "örn.", "vb."}:
                next_match = re.search(boundary, self.pending[cut:])
                cut = cut + next_match.end() if next_match else 0
            if not cut and len(self.pending) >= self.max_chars:
                cut = self.pending.rfind(" ", 0, self.max_chars)
                cut = cut if cut > 30 else self.max_chars
            if not cut and final:
                cut = len(self.pending)
            if not cut:
                break
            piece, self.pending = self.pending[:cut].strip(), self.pending[cut:].lstrip()
            if piece:
                result.append(piece)
        return result
