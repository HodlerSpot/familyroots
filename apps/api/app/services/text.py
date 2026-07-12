"""Copy helpers: natural phrasing around user-provided names."""


def family_phrase(name: str) -> str:
    """Wrap a family name for use mid-sentence ("...join {phrase}...") without
    doubling articles or the word family:
      "Smith"             -> "the Smith family"
      "The Saliga Family" -> "The Saliga Family"
      "Saliga Family"     -> "the Saliga Family"
    """
    phrase = name.strip()
    if not phrase.lower().endswith("family"):
        phrase = f"{phrase} family"
    if not name.strip().lower().startswith("the "):
        phrase = f"the {phrase}"
    return phrase
