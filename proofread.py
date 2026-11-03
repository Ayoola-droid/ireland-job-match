"""Automatic proofreading for AI-written text (offline: nothing leaves your laptop).

Fixed automatically (and listed, so you can see every change):
  - words run together, e.g. 'myskills' -> 'my skills' (lower-case words only)
  - a missing space after punctuation, e.g. 'totals.At' -> 'totals. At'
  - doubled words ('the the') and double spaces
Flagged for you to check (never changed):
  - words not in the dictionary, with a suggestion
  - American spellings in an Irish/UK application, e.g. 'analyze' -> 'analyse'
Words from your CV, the job ad and the skills list (Mailchimp, Fadare, HubSpot...) count as
correct, so names aren't flagged. Uses the free pyspellchecker dictionary, extended with UK spellings.
"""
import re

from spellchecker import SpellChecker

MIN_FREQUENCY = 50  # how common a word must be to count as one half of a split ('my' + 'skills')

# Common US -> UK pairs that the -ize/-yze rules below don't cover
US_TO_UK = {
    "color": "colour", "colors": "colours", "favor": "favour", "favorite": "favourite", "behavior": "behaviour",
    "behaviors": "behaviours", "labor": "labour", "honor": "honour", "neighbor": "neighbour", "humor": "humour",
    "flavor": "flavour", "center": "centre", "centers": "centres", "theater": "theatre", "catalog": "catalogue",
    "traveled": "travelled", "traveling": "travelling", "modeling": "modelling", "modeled": "modelled",
    "labeled": "labelled", "labeling": "labelling", "canceled": "cancelled", "enrollment": "enrolment",
    "fulfill": "fulfil", "judgment": "judgement", "gray": "grey",
}
EXTRA_UK_WORDS = ["multi", "programme", "programmes", "licence", "defence", "datasets", "dataset", "workflow", "workflows",
                  "upskilling", "reskilling", "organisational", "analytics"]
NOT_IZE = {"size", "sizes", "seize", "seized", "prize", "prizes", "capsize", "baize", "maize", "assize"}

_checker = None
_uk_words = set()


def _uk_variant(word):
    """'analyze' -> 'analyse', 'optimizing' -> 'optimising' (None if the rules don't apply)."""
    if word in US_TO_UK:
        return US_TO_UK[word]
    if word in NOT_IZE:
        return None
    for pattern, replacement in [(r"yz(e|es|ed|ing|er|ers)$", r"ys\1"),
                                 (r"iz(e|es|ed|ing|er|ers|ation|ations|ational)$", r"is\1")]:
        if re.search(pattern, word):
            return re.sub(pattern, replacement, word)
    return None


def checker():
    """The spell-checker, loaded once, with UK spellings added."""
    global _checker
    if _checker is None:
        _checker = SpellChecker(language="en")
        words = _checker.word_frequency.dictionary
        for w, freq in list(words.items()):
            variant = _uk_variant(w) if freq >= 20 else None
            if variant and variant != w:
                _uk_words.add(variant)
        _uk_words.update(US_TO_UK.values())
        _uk_words.update(EXTRA_UK_WORDS)
        _checker.word_frequency.load_words(sorted(_uk_words))
    return _checker


def known_words(*texts):
    """Every word in these texts counts as correctly spelled (names, tools, places)."""
    found = set()
    for text in texts:
        found.update(w.lower() for w in re.findall(r"[A-Za-z][A-Za-z'-]*", str(text)))
    return found


def _is_known(word, known):
    w = word.lower()
    if w in known or w in checker():
        return True
    # plurals and possessives of known words: 'functionalities', 'stakeholder's'
    for stem in (w[:-1], w[:-2], w[:-3] + "y", w[:-2] if w.endswith("'s") else ""):
        if stem and (stem in known or stem in checker()):
            return True
    return False


def _best_split(word, known):
    """'myskills' -> ('my', 'skills') if both halves are common words, else None."""
    sp, best, best_score = checker(), None, 0
    for i in range(2, len(word) - 1):
        left, right = word[:i], word[i:]
        if len(right) < 2:
            continue
        lf = sp.word_frequency[left] or (10 ** 6 if left in known else 0)
        rf = sp.word_frequency[right] or (10 ** 6 if right in known else 0)
        score = min(lf, rf)
        if score >= MIN_FREQUENCY and score > best_score:
            best, best_score = (left, right), score
    return best


def proofread(text, known=()):
    """Return (corrected_text, list_of_fixes, list_of_flags)."""
    known = {k.lower() for k in known}
    fixes, flags = [], []

    # 1. Missing space after punctuation: 'totals.At' -> 'totals. At'
    def add_space(m):
        fixes.append(f"added a space after '{m.group(1)}{m.group(2)}'")
        return f"{m.group(1)}{m.group(2)} {m.group(3)}"
    text = re.sub(r"([a-z]{2,})([.!?,;:])([A-Z])", add_space, text)

    # 2. Double spaces (line breaks are kept)
    text = re.sub(r"[ \t]{2,}", " ", text)

    # 3. Doubled words: 'the the' -> 'the'
    def undouble(m):
        fixes.append(f"removed a doubled word: '{m.group(0)}'")
        return m.group(1)
    text = re.sub(r"\b([A-Za-z]+)\s+\1\b", undouble, text, flags=re.IGNORECASE)

    # 4. Words run together, and spelling
    def check_word(m):
        word = m.group(0)
        if (_is_known(word, known) or word.isupper() or re.fullmatch(r"[A-Z]{2,}s", word)
                or re.search(r"[a-z][A-Z]", word)):
            return word  # known, an acronym (KPI, KPIs) or CamelCase (HubSpot)
        split = _best_split(word.lower(), known)
        if split and word.islower():
            fixes.append(f"split joined words: '{word}' -> '{split[0]} {split[1]}'")
            return f"{split[0]} {split[1]}"
        if split:
            flags.append(f"'{word}' may be two words run together ('{split[0]} {split[1]}'?)")
        elif len(word) >= 3:
            suggestion = checker().correction(word.lower())
            flags.append(f"'{word}' is not in the dictionary" + (f" (did you mean '{suggestion}'?)"
                                                                if suggestion and suggestion != word.lower() else ""))
        return word
    text = re.sub(r"(?<![\[\w])[A-Za-z]+(?:'[a-z]+)?(?![\w\]])", check_word, text)

    # 5. American spellings
    for word in sorted(set(re.findall(r"\b[a-z]+\b", text.lower()))):
        variant = _uk_variant(word)
        if variant and variant != word and variant in _uk_words and word not in known:
            flags.append(f"American spelling '{word}': UK/Irish spelling is '{variant}'")

    counted = [f + (f" (x{fixes.count(f)})" if fixes.count(f) > 1 else "") for f in dict.fromkeys(fixes)]
    return text, counted, list(dict.fromkeys(flags))
