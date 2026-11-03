"""Find the questions in an employer's application form (.docx), and whether the form forbids AI.

Application forms mix instructions (how to email it, data privacy, declarations) with the few
questions you must answer, usually written as "Please demonstrate your experience of ...",
"Describe a time when ..." or "Give an example of ...". This keeps only those questions.

Some employers do not allow AI-written answers. The HSE's forms say: "Your application must be
your own work ... Do not use AI to complete the application form." When a form says this, the
app does not write the answers; it makes an answer plan instead (the best examples from your CV
for each question, under Situation / Task / Action / Result headings) for you to write yourself.
"""
import io
import re
import zipfile
from html import unescape

QUESTION_START = re.compile(
    r"^(?:\d+[.)]\s*)?(?:please\s+)?(?:demonstrate|describe|outline|explain|detail (?:how|your|an?)|tell us|"
    r"give (?:us )?(?:an|one|a specific|two) example|provide (?:us with )?(?:an|a specific|one) example|"
    r"using (?:an|a specific) example|in (?:no more than )?\d+ words)", re.I)
ADMIN = re.compile(r"\bemail|application form|attach|closing date|signature|declaration|referee|"
                   r"the space provided|data protection|privacy", re.I)
NO_AI = re.compile(r"do not use (?:any )?(?:AI|artificial intelligence|generative)|"
                   r"(?:must|should) not (?:be )?(?:use|written|generated|completed)\w* (?:using |with |by )?"
                   r"(?:AI|artificial intelligence|generative)|without (?:the )?(?:use|help) of (?:AI|artificial)|"
                   r"use of (?:AI|artificial intelligence|generative AI)[^.]{0,40}(?:not (?:permitted|allowed)|prohibited)",
                   re.I)


def paragraphs(content):
    """Every paragraph of a .docx (including inside tables), in order, as plain text.
    `content` is the file's bytes, or a path to it."""
    if isinstance(content, (str, bytes)) and not (isinstance(content, bytes) and content[:2] == b"PK"):
        content = open(content, "rb").read()
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
    texts = []
    for para in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S):
        text = unescape("".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", para)))
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            texts.append(text)
    return texts


def questions_from_docx(content):
    """The questions to answer, in the order they appear, without repeats."""
    found = []
    for text in paragraphs(content):
        if (len(text) >= 50 and QUESTION_START.search(text) and re.search(r"\byou(?:r)?\b", text, re.I)
                and not ADMIN.search(text) and text not in found):
            found.append(text)
    return found


def forbids_ai(content):
    """True when the form says not to use AI to complete it."""
    return any(NO_AI.search(text) for text in paragraphs(content))


def word_limit(question, default=250):
    """'Please limit your answer to 300 words' -> 300; '1 page' -> about 450 words."""
    words = re.search(r"(\d{2,4})\s*words", question, re.I)
    if words:
        return int(words.group(1))
    pages = re.search(r"(\d+)\s*pages?", question, re.I)
    return int(pages.group(1)) * 450 if pages else default


if __name__ == "__main__":
    import sys
    for path in sys.argv[1:]:
        print(path, "| forbids AI:", forbids_ai(path))
        for i, q in enumerate(questions_from_docx(path), 1):
            print(f"  {i}. {q}  (about {word_limit(q)} words)")
