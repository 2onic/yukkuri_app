"""
多语种油库里空耳映射引擎 (Polyglot G2P)
支持中文拼音转写、英文音节外来语化与日文原生假名纠偏
"""

import re
from typing import Dict, Optional
import pykakasi
import pypinyin

from yukkuri.g2p.dicts.pinyin import PINYIN_MAP
from yukkuri.g2p.dicts.english import (
    ENGLISH_HIGH_FREQ,
    LETTER_MAP,
    ENG_VOWELS,
    ENG_CONSONANTS,
    ENG_SYLLABLES,
)
from yukkuri.g2p.normalizer import (
    normalize_digits,
    normalize_punctuations,
    clean_koe_string,
)

def english_to_kana(word: str, custom_vocab: Optional[Dict[str, str]] = None) -> str:
    """英文单词转假名"""
    w = word.lower().strip()
    if not w:
        return ""

    if custom_vocab and w in custom_vocab:
        return custom_vocab[w]

    if w in ENGLISH_HIGH_FREQ:
        return ENGLISH_HIGH_FREQ[w]

    # 短无元音缩写（如 CPU, IP, PC 等）按字母逐个拼读
    if len(w) <= 3 and not any(v in w for v in 'aeiou'):
        return '/'.join([LETTER_MAP.get(c, '') for c in w if c in LETTER_MAP])

    i = 0
    res = []
    while i < len(w):
        if i + 3 <= len(w) and w[i:i+3] in ENG_SYLLABLES:
            res.append(ENG_SYLLABLES[w[i:i+3]])
            i += 3
        elif i + 2 <= len(w) and w[i:i+2] in ENG_SYLLABLES:
            res.append(ENG_SYLLABLES[w[i:i+2]])
            i += 2
        elif w[i] in ENG_VOWELS:
            res.append(ENG_VOWELS[w[i]])
            i += 1
        elif w[i] in ENG_CONSONANTS:
            res.append(ENG_CONSONANTS[w[i]])
            i += 1
        else:
            if w[i] in LETTER_MAP:
                res.append(LETTER_MAP[w[i]])
            i += 1
    return ''.join(res)


class PolyglotG2P:
    """多语种转油库里音标处理器"""

    def __init__(self, custom_dict: Optional[Dict[str, str]] = None):
        self._kakasi = pykakasi.kakasi()
        self.custom_dict: Dict[str, str] = custom_dict or {}

    def add_custom_rule(self, word: str, kana: str):
        self.custom_dict[word.lower()] = kana

    def convert(self, text: str, lang: str = "zh") -> str:
        """将任意多语种混合文本转换为 AquesTalk 假名音标"""
        if not text:
            return ""

        tokens = []
        pattern = re.compile(r'([a-zA-Z]+|[\u3040-\u309f\u30a0-\u30ff]+|[\u4e00-\u9fa5]+|[0-9]+|[，。！？、?.,!/]+)')
        parts = pattern.findall(text)

        for part in parts:
            if not part:
                continue

            # 用户自定义词匹配
            part_lower = part.lower()
            if part_lower in self.custom_dict:
                tokens.append(self.custom_dict[part_lower])
                continue

            # 英文处理
            if re.match(r'^[a-zA-Z]+$', part):
                kana = english_to_kana(part, custom_vocab=self.custom_dict)
                if kana:
                    tokens.append(kana)
            # 数字处理
            elif re.match(r'^[0-9]+$', part):
                num_kana = normalize_digits(part, lang=lang)
                if num_kana:
                    tokens.append(num_kana)
            # 日文原生假名
            elif re.match(r'^[\u3040-\u309f\u30a0-\u30ff]+$', part):
                tokens.append(part)
            # 中文汉字
            elif re.match(r'^[\u4e00-\u9fa5]+$', part):
                if lang == "ja":
                    res = self._kakasi.convert(part)
                    for item in res:
                        orig = item.get('orig', '')
                        hira = item.get('hira', '')
                        # 日语助词发音纠正 (は -> わ, へ -> え)
                        if orig == 'は' or hira == 'は':
                            hira = 'わ'
                        elif orig == 'へ' or hira == 'へ':
                            hira = 'え'
                        tokens.append(hira)
                else:
                    part_conv = part.replace('油库里', 'ゆっくり')
                    py_list = pypinyin.lazy_pinyin(part_conv)
                    for py in py_list:
                        kana = PINYIN_MAP.get(py, py)
                        tokens.append(kana)
            # 标点符号与停顿
            elif re.match(r'^[，。！？、?.,!/]+$', part):
                tokens.append(normalize_punctuations(part))

        raw_koe = '/'.join(tokens)
        return clean_koe_string(raw_koe)


# 默认单例与便捷调用函数
_default_g2p = PolyglotG2P()

def text_to_yukkuri_polyglot(text: str, current_lang: str = "zh") -> str:
    return _default_g2p.convert(text, lang=current_lang)
