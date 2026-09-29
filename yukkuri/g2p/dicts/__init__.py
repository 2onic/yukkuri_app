"""
G2P Phonetic and Kana dictionaries for Yukkuri speech mapping.
"""

from yukkuri.g2p.dicts.pinyin import PINYIN_MAP
from yukkuri.g2p.dicts.english import (
    ENGLISH_HIGH_FREQ,
    LETTER_MAP,
    ENG_VOWELS,
    ENG_CONSONANTS,
    ENG_SYLLABLES,
)

__all__ = [
    "PINYIN_MAP",
    "ENGLISH_HIGH_FREQ",
    "LETTER_MAP",
    "ENG_VOWELS",
    "ENG_CONSONANTS",
    "ENG_SYLLABLES",
]
