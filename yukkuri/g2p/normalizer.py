"""
文本预处理与标点符号/数字归一化
"""

import re

DIGIT_CN = {
    '0': 'りん', '1': 'いー', '2': 'あー', '3': 'さん', '4': 'すー',
    '5': 'うー', '6': 'りう', '7': 'ちー', '8': 'ばー', '9': 'じう'
}

DIGIT_JA = {
    '0': 'ゼロ', '1': 'イチ', '2': 'ニ', '3': 'サン', '4': 'ヨン',
    '5': 'ゴ', '6': 'ロク', '7': 'ナナ', '8': 'ハチ', '9': 'キュウ'
}

def normalize_digits(digits: str, lang: str = "zh") -> str:
    """将数字字符串按语种转换为假名序列"""
    digit_map = DIGIT_JA if lang == "ja" else DIGIT_CN
    tokens = [digit_map.get(d, '') for d in digits if d in digit_map]
    return '/'.join(tokens)

def normalize_punctuations(text: str) -> str:
    """统一中文与英文标点符号为 AquesTalk 能接受的停顿符"""
    return (
        text.replace('！', '。')
        .replace('!', '。')
        .replace('，', '、')
        .replace(',', '、')
        .replace('.', '。')
    )

def clean_koe_string(raw_koe: str) -> str:
    """
    清理音标串：
    - 移除不合法字符（仅保留日文假名、顿号、句号、长音符、问号与斜杠分隔符）
    - 合并重复顿号与斜杠
    - 消除边界无效字符
    """
    clean = re.sub(r'[\s\t\r\n]+', '/', raw_koe)
    clean = re.sub(r'[^\u3040-\u309f\u30a0-\u30ff、。？?ー/\']', '', clean)
    clean = re.sub(r'/+', '/', clean)
    clean = re.sub(r'/([、。？?])', r'\1', clean)
    clean = re.sub(r'([、。？?])/', r'\1', clean)
    clean = re.sub(r'、+', '、', clean)
    clean = re.sub(r'。+', '。', clean)
    return clean.strip('/、')
