#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
油库里 (Yukkuri) 实时语音转换器
支持 SenseVoice 与 Vosk 双引擎
"""

import os
import sys
import json
import ctypes
import re
import queue
import threading
import argparse
import subprocess
import signal
import numpy as np

# 检查依赖
try:
    import sounddevice as sd
    import pykakasi
    import pypinyin
except ImportError as e:
    print(f"[环境错误] 缺少必要依赖: {e}")
    print("请确认已激活 conda 环境，例如：")
    print("  conda activate yukkuri")
    print("  或者使用完整路径运行: /home/colimy/miniforge3/envs/yukkuri/bin/python yukkuri_bridge.py")
    sys.exit(1)

# 可选引擎依赖
try:
    import sherpa_onnx
    HAS_SHERPA = True
except ImportError:
    HAS_SHERPA = False

try:
    from vosk import Model, KaldiRecognizer
    HAS_VOSK = True
except ImportError:
    HAS_VOSK = False

script_dir = os.path.dirname(os.path.abspath(__file__))

# ==========================================
# 1. 加载 AquesTalk1 动态库 (Linux x86_64)
# ==========================================
so_candidates = [
    os.path.join(script_dir, "libAquesTalk.so.1"),
    os.path.join(script_dir, "libAquesTalk.so"),
    os.path.abspath("./libAquesTalk.so.1"),
    os.path.abspath("./libAquesTalk.so"),
]

so_path = None
for candidate in so_candidates:
    if os.path.exists(candidate):
        so_path = candidate
        break

if not so_path:
    print(f"[严重错误] 未找到 libAquesTalk.so 动态库！")
    sys.exit(1)

try:
    aq = ctypes.cdll.LoadLibrary(so_path)
except Exception as e:
    print(f"[严重错误] 无法加载动态库 {so_path}: {e}")
    sys.exit(1)

if hasattr(aq, 'AquesTalk_Synthe_Utf8'):
    aq_synthe_fn = aq.AquesTalk_Synthe_Utf8
    use_utf8 = True
else:
    aq_synthe_fn = aq.AquesTalk_Synthe
    use_utf8 = False

aq_synthe_fn.restype = ctypes.POINTER(ctypes.c_ubyte)
aq_synthe_fn.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
aq.AquesTalk_FreeWave.argtypes = [ctypes.POINTER(ctypes.c_ubyte)]

AQUESTALK_ERROR_MAP = {
    100: "その他のエラー (Other error)",
    101: "メモリ不足 (Out of memory)",
    102: "音記号列の長さ制限オーバー (Koe string too long)",
    103: "音記号列が空 (Empty koe string)",
    104: "初期化されていない (Not initialized)",
    105: "音声記号列に未定義の読み記号が指定された (Undefined phonetic symbol)",
    106: "ポーズ長オーバー (Pause too long)",
    107: "音記号列の指定フォーマット不正 (Invalid format)",
}

# ==========================================
# 2. 多语种油库里音标映射引擎 (Polyglot G2P)
# ==========================================
kakasi = pykakasi.kakasi()

ENGLISH_HIGH_FREQ = {
    'hello': 'へろー', 'hi': 'はい', 'hey': 'へい', 'bye': 'ばいばい', 'goodbye': 'ぐっどばい',
    'thanks': 'さんくす', 'thank': 'さんく', 'you': 'ゆー', 'yes': 'いえす', 'no': 'のー',
    'ok': 'おーけー', 'okay': 'おーけー', 'please': 'ぷりーず', 'sorry': 'そりー',
    'good': 'ぐっど', 'bad': 'ばっど', 'nice': 'ないす', 'cool': 'くーる',
    'game': 'げーむ', 'play': 'ぷれい', 'start': 'すたーと', 'stop': 'すとっぷ',
    'wait': 'うぇいと', 'help': 'へるぷ', 'win': 'うぃん', 'lose': 'るーず',
    'discord': 'でぃすこーど', 'steam': 'すちーむ', 'youtube': 'ゆーちゅーぶ',
    'live': 'らいぶ', 'mic': 'まいく', 'sound': 'さうんど', 'test': 'てすと',
    'world': 'わーるど', 'happy': 'はっぴー', 'gg': 'じーじー', 'lol': 'えるおーえる',
    'ready': 'れでぃ', 'go': 'ごー', 'run': 'らん', 'fast': 'ふぁすと',
    'python': 'ぱいそん', 'linux': 'りなくす', 'windows': 'うぃんどーず',
    'voice': 'ぼいす', 'chat': 'ちゃっと', 'cpu': 'しーぴーゆー', 'gpu': 'じーぴーゆー',
    'ai': 'えーあい', 'id': 'あいでぃー', 'ip': 'あいぴー', 'pc': 'ぴーしー',
    'bro': 'ぶろ', 'friend': 'ふれんど', 'see': 'しー', 'later': 'れいたー',
    'much': 'まち', 'very': 'べりー', 'one': 'わん', 'two': 'つー', 'three': 'すりー',
    'kill': 'きる', 'die': 'だい', 'boss': 'ぼす', 'pro': 'ぷろ', 'noob': 'ぬーぶ',
}

LETTER_MAP = {
    'a': 'えー', 'b': 'びー', 'c': 'しー', 'd': 'でぃー', 'e': 'いー',
    'f': 'えふ', 'g': 'じー', 'h': 'えいち', 'i': 'あい', 'j': 'じぇー',
    'k': 'けー', 'l': 'える', 'm': 'えむ', 'n': 'えぬ', 'o': 'おー',
    'p': 'ぴー', 'q': 'きゅー', 'r': 'あーる', 's': 'えす', 't': 'てぃー',
    'u': 'ゆー', 'v': 'ぶい', 'w': 'だぶりゅー', 'x': 'えっくす',
    'y': 'わい', 'z': 'ぜっと'
}

ENG_VOWELS = {'a': 'あ', 'e': 'え', 'i': 'い', 'o': 'お', 'u': 'う'}
ENG_CONSONANTS = {
    'b': 'ぶ', 'c': 'く', 'd': 'ど', 'f': 'ふ', 'g': 'ぐ', 'h': 'は',
    'j': 'じ', 'k': 'く', 'l': 'る', 'm': 'む', 'n': 'ん', 'p': 'ぷ',
    'q': 'く', 'r': 'る', 's': 'す', 't': 'と', 'v': 'ぶ', 'w': 'う',
    'x': 'くす', 'y': 'い', 'z': 'ず'
}

ENG_SYLLABLES = {
    'ba': 'ば', 'be': 'べ', 'bi': 'び', 'bo': 'ぼ', 'bu': 'ぶ',
    'pa': 'ぱ', 'pe': 'ぺ', 'pi': 'ぴ', 'po': 'ぽ', 'pu': 'ぷ',
    'ma': 'ま', 'me': 'め', 'mi': 'み', 'mo': 'も', 'mu': 'む',
    'fa': 'ふぁ', 'fe': 'ふぇ', 'fi': 'ふぃ', 'fo': 'ふぉ', 'fu': 'ふ',
    'da': 'だ', 'de': 'で', 'di': 'でぃ', 'do': 'ど', 'du': 'どぅ',
    'ta': 'た', 'te': 'て', 'ti': 'てぃ', 'to': 'と', 'tu': 'つ',
    'na': 'な', 'ne': 'ね', 'ni': 'に', 'no': 'の', 'nu': 'ぬ',
    'la': 'ら', 'le': 'れ', 'li': 'り', 'lo': 'ろ', 'lu': 'る',
    'ra': 'ら', 're': 'れ', 'ri': 'り', 'ro': 'ろ', 'ru': 'る',
    'ga': 'が', 'ge': 'げ', 'gi': 'ぎ', 'go': 'ご', 'gu': 'ぐ',
    'ka': 'か', 'ke': 'け', 'ki': 'き', 'ko': 'こ', 'ku': 'く',
    'ha': 'は', 'he': 'へ', 'hi': 'ひ', 'ho': 'ほ', 'hu': 'ふ',
    'za': 'ざ', 'ze': 'ぜ', 'zi': 'じ', 'zo': 'ぞ', 'zu': 'ず',
    'sa': 'さ', 'se': 'せ', 'si': 'し', 'so': 'そ', 'su': 'す',
    'sha': 'しゃ', 'she': 'しぇ', 'shi': 'し', 'sho': 'しょ', 'shu': 'しゅ',
    'cha': 'ちゃ', 'che': 'ちぇ', 'chi': 'ち', 'cho': 'ちょ', 'chu': 'ちゅ',
    'tha': 'さ', 'the': 'ざ', 'thi': 'し', 'tho': 'そ', 'thu': 'す',
    'ya': 'や', 'ye': 'いえ', 'yo': 'よ', 'yu': 'ゆ',
    'wa': 'わ', 'we': 'うぇ', 'wi': 'うぃ', 'wo': 'うぉ'
}

def english_to_kana(word: str) -> str:
    w = word.lower().strip()
    if not w:
        return ""
    if w in ENGLISH_HIGH_FREQ:
        return ENGLISH_HIGH_FREQ[w]
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

PINYIN_MAP = {
    'a': 'あー', 'o': 'おー', 'e': 'えー', 'ai': 'あい', 'ei': 'えい', 'ao': 'あお', 'ou': 'おう',
    'an': 'あん', 'en': 'えん', 'ang': 'あん', 'eng': 'えん', 'er': 'あーる',
    'ba': 'ばー', 'bo': 'ぼー', 'bai': 'ばい', 'bei': 'べい', 'bao': 'ばお', 'ban': 'ばん', 'ben': 'べん', 'bang': 'ばん', 'beng': 'べん', 'bi': 'びー', 'bie': 'びえ', 'biao': 'びあお', 'bian': 'びあん', 'bin': 'びん', 'bing': 'びん', 'bu': 'ぶー',
    'pa': 'ぱー', 'po': 'ぽー', 'pai': 'ぱい', 'pei': 'ぺい', 'pao': 'ぱお', 'pou': 'ぽう', 'pan': 'ぱん', 'pen': 'ぺん', 'pang': 'ぱん', 'peng': 'ぺん', 'pi': 'ぴー', 'pie': 'ぴえ', 'piao': 'ぴあお', 'pian': 'ぴあん', 'pin': 'ぴん', 'ping': 'ぴん', 'pu': 'ぷー',
    'ma': 'まー', 'mo': 'もー', 'me': 'ま', 'mai': 'まい', 'mei': 'めい', 'mao': 'まお', 'mou': 'もう', 'man': 'まん', 'men': 'めん', 'mang': 'まん', 'meng': 'めん', 'mi': 'みー', 'mie': 'みえ', 'miao': 'みあお', 'miu': 'みう', 'mian': 'みあん', 'min': 'みん', 'ming': 'みん', 'mu': 'むー',
    'fa': 'ふぁー', 'fo': 'ふぉー', 'fei': 'ふぇい', 'fou': 'ふぉう', 'fan': 'ふぁん', 'fen': 'ふぇん', 'fang': 'ふぁん', 'feng': 'ふぇん', 'fu': 'ふー',
    'da': 'だー', 'de': 'だ', 'dai': 'だい', 'dei': 'でい', 'dao': 'だお', 'dou': 'どう', 'dan': 'だん', 'dang': 'だん', 'deng': 'でん', 'di': 'でぃー', 'die': 'でぃえ', 'diao': 'でぃあお', 'diu': 'でぃう', 'dian': 'でぃあん', 'ding': 'でぃん', 'dong': 'どん', 'du': 'どぅー', 'duan': 'どぅあん', 'dui': 'どぅい', 'dun': 'どぅん', 'duo': 'どぅお',
    'ta': 'たー', 'te': 'た', 'tai': 'たい', 'tao': 'たお', 'tou': 'とう', 'tan': 'たん', 'tang': 'たん', 'teng': 'てん', 'ti': 'てぃー', 'tie': 'てぃえ', 'tiao': 'てぃあお', 'tian': 'てぃあん', 'ting': 'てぃん', 'tong': 'とん', 'tu': 'とぅー', 'tuan': 'とぅあん', 'tui': 'とぅい', 'tun': 'とぅん', 'tuo': 'とぅお',
    'na': 'なー', 'ne': 'ね', 'nai': 'ない', 'nei': 'ねい', 'nao': 'なお', 'nou': 'のう', 'nan': 'なん', 'nen': 'ねん', 'nang': 'なん', 'neng': 'ねん', 'ni': 'にー', 'nie': 'にえ', 'niao': 'ニアオ', 'niu': 'にう', 'nian': 'にあん', 'nin': 'にん', 'niang': 'にあん', 'ning': 'にん', 'nong': 'のん', 'nu': 'ぬー', 'nuan': 'ぬあん', 'nuo': 'ぬお', 'nü': 'にゅー', 'nue': 'にゅえ',
    'la': 'らー', 'le': 'ら', 'lai': 'らい', 'lei': 'れい', 'lao': 'らお', 'lou': 'ろう', 'lan': 'らん', 'lang': 'らん', 'leng': 'れん', 'li': 'りー', 'lia': 'りあ', 'lie': 'りえ', 'liao': 'りあお', 'liu': 'りう', 'lian': 'りあん', 'lin': 'りん', 'liang': 'りあん', 'ling': 'りん', 'long': 'ろん', 'lu': 'るー', 'luan': 'るあん', 'lun': 'るん', 'luo': 'るお', 'lü': 'りゅー', 'lue': 'りゅえ',
    'ga': 'がー', 'ge': 'が', 'gai': 'がい', 'gei': 'げい', 'gao': 'がお', 'gou': 'ごう', 'gan': 'がん', 'gen': 'げん', 'gang': 'がん', 'geng': 'げん', 'gong': 'ごん', 'gu': 'ぐー', 'gua': 'ぐあ', 'guo': 'ぐお', 'guai': 'ぐあい', 'gui': 'ぐい', 'guan': 'ぐあん', 'gun': 'ぐん', 'guang': 'ぐあん',
    'ka': 'かー', 'ke': 'か', 'kai': 'かい', 'kei': 'けい', 'kao': 'かお', 'kou': 'こう', 'kan': 'かん', 'ken': 'けん', 'kang': 'かん', 'keng': 'けん', 'kong': 'こん', 'ku': 'くー', 'kua': 'くあ', 'kuo': 'くお', 'kuai': 'くあい', 'kui': 'くい', 'kuan': 'くあん', 'kun': 'くん', 'kuang': 'くあん',
    'ha': 'はー', 'he': 'は', 'hai': 'はい', 'hei': 'へい', 'hao': 'はお', 'hou': 'ほう', 'han': 'はん', 'hen': 'へん', 'hang': 'はん', 'heng': 'へん', 'hong': 'ほん', 'hu': 'ふー', 'hua': 'ふあ', 'huo': 'ふお', 'huai': 'ふあい', 'hui': 'ふい', 'huan': 'ふあん', 'hun': 'ふん', 'huang': 'ふあん',
    'ji': 'じー', 'jia': 'じあ', 'jie': 'じえ', 'jiao': 'じあお', 'jiu': 'じう', 'jian': 'じあん', 'jin': 'じん', 'jiang': 'じあん', 'jing': 'じん', 'jiong': 'じおん', 'ju': 'じゅー', 'juan': 'じゅあん', 'jun': 'じゅん', 'jue': 'じゅえ',
    'qi': 'ちー', 'qia': 'ちあ', 'qie': 'ちえ', 'qiao': 'ちあお', 'qiu': 'ちう', 'qian': 'ちあん', 'qin': 'ちん', 'qiang': 'ちあん', 'qing': 'ちん', 'qiong': 'ちおん', 'qu': 'ちゅー', 'quan': 'ちゅあん', 'qun': 'ちゅん', 'que': 'ちゅえ',
    'xi': 'しー', 'xia': 'しあ', 'xie': 'しえ', 'xiao': 'しあお', 'xiu': 'しう', 'xian': 'しあん', 'xin': 'しん', 'xiang': 'しあん', 'xing': 'しん', 'xiong': 'しおん', 'xu': 'しゅー', 'xuan': 'しゅあん', 'xun': 'しゅん', 'xue': 'しゅえ',
    'zhi': 'じー', 'zha': 'ざー', 'zhe': 'ざ', 'zhai': 'ざい', 'zhei': 'ぜい', 'zhao': 'ざお', 'zhou': 'ぞう', 'zhan': 'ざん', 'zhen': 'ぜん', 'zhang': 'ざん', 'zheng': 'ぜん', 'zhong': 'ぞん', 'zhu': 'ずー', 'zhua': 'ずあ', 'zhuo': 'ずお', 'zhuai': 'ずあい', 'zhui': 'ずい', 'zhuan': 'ずあん', 'zhun': 'ずん', 'zhuang': 'ずあん',
    'chi': 'ちー', 'cha': 'ちゃー', 'che': 'ちぇ', 'chai': 'ちゃい', 'chao': 'ちゃお', 'chou': 'ちょう', 'chan': 'ちゃん', 'chen': 'ちぇん', 'chang': 'ちゃん', 'cheng': 'ちぇん', 'chong': 'ちょん', 'chu': 'ちゅー', 'chua': 'ちゅあ', 'chuo': 'ちゅお', 'chuai': 'ちゅあい', 'chui': 'ちゅい', 'chuan': 'ちゅあん', 'chun': 'ちゅん', 'chuang': 'ちゅあん',
    'shi': 'しー', 'sha': 'しゃー', 'she': 'しぇ', 'shai': 'しゃい', 'shei': 'しぇい', 'shao': 'しゃお', 'shou': 'しょう', 'shan': 'しゃん', 'shen': 'しぇん', 'shang': 'しゃん', 'sheng': 'しぇん', 'shu': 'しゅー', 'shua': 'しゅあ', 'shuo': 'しゅお', 'shuai': 'しゅあい', 'shui': 'しゅい', 'shuan': 'しゅあん', 'shun': 'しゅん', 'shuang': 'しゅあん',
    'ri': 'りー', 're': 'ら', 'rao': 'らお', 'rou': 'ろう', 'ran': 'らん', 'ren': 'れん', 'rang': 'らん', 'reng': 'れん', 'rong': 'ろん', 'ru': 'るー', 'rua': 'るあ', 'ruo': 'るお', 'rui': 'るい', 'ruan': 'るあん', 'run': 'るん',
    'za': 'ざー', 'ze': 'ざ', 'zai': 'ざい', 'zei': 'ぜい', 'zao': 'ざお', 'zou': 'ぞう', 'zan': 'ざん', 'zen': 'ぜん', 'zang': 'ざん', 'zeng': 'ぜん', 'zong': 'ぞん', 'zu': 'ずー', 'zuan': 'ずあん', 'zui': 'ずい', 'zun': 'ずん', 'zuo': 'ずお', 'zi': 'ずー',
    'ca': 'つぁー', 'ce': 'つぇ', 'cai': 'つぁい', 'cao': 'つぁお', 'cou': 'つぉう', 'can': 'つぁん', 'cen': 'つぇん', 'cang': 'つぁん', 'ceng': 'つぇん', 'cong': 'つぉん', 'cu': 'つー', 'cuan': 'つあん', 'cui': 'つい', 'cun': 'つん', 'cuo': 'つお', 'ci': 'つー',
    'sa': 'さー', 'se': 'せ', 'sai': 'さい', 'sao': 'さお', 'sou': 'そう', 'san': 'さん', 'sen': 'せん', 'sang': 'さん', 'seng': 'せん', 'song': 'そん', 'su': 'すー', 'suan': 'すあん', 'sui': 'すい', 'sun': 'すん', 'suo': 'すお', 'si': 'すー',
    'ya': 'やー', 'yao': 'やお', 'ye': 'いえ', 'you': 'よう', 'yan': 'いあん', 'yang': 'いあん', 'yin': 'いん', 'ying': 'いん', 'yong': 'いおん', 'yi': 'いー',
    'wa': 'わー', 'wo': 'うぉ', 'wai': 'わい', 'wei': 'うぇい', 'wan': 'わん', 'wen': 'うぇん', 'wang': 'わん', 'weng': 'うぇん', 'wu': 'うー',
    'yu': 'ゆー', 'yuan': 'ゆあん', 'yue': 'ゆえ', 'yun': 'ゆん'
}

DIGIT_CN = {'0': 'りん', '1': 'いー', '2': 'あー', '3': 'さん', '4': 'すー', '5': 'うー', '6': 'りう', '7': 'ちー', '8': 'ばー', '9': 'じう'}
DIGIT_JA = {'0': 'ゼロ', '1': 'イチ', '2': 'ニ', '3': 'サン', '4': 'ヨン', '5': 'ゴ', '6': 'ロク', '7': 'ナナ', '8': 'ハチ', '9': 'キュウ'}

def text_to_yukkuri_polyglot(text: str, current_lang: str = "zh") -> str:
    if not text:
        return ""

    tokens = []
    pattern = re.compile(r'([a-zA-Z]+|[\u3040-\u309f\u30a0-\u30ff]+|[\u4e00-\u9fa5]+|[0-9]+|[，。！？、?.,!/]+)')
    parts = pattern.findall(text)

    for part in parts:
        if not part:
            continue
        if re.match(r'^[a-zA-Z]+$', part):
            kana = english_to_kana(part)
            if kana:
                tokens.append(kana)
        elif re.match(r'^[0-9]+$', part):
            digit_map = DIGIT_JA if current_lang == "ja" else DIGIT_CN
            num_tokens = [digit_map.get(d, '') for d in part]
            tokens.append('/'.join(num_tokens))
        elif re.match(r'^[\u3040-\u309f\u30a0-\u30ff]+$', part):
            tokens.append(part)
        elif re.match(r'^[\u4e00-\u9fa5]+$', part):
            if current_lang == "ja":
                res = kakasi.convert(part)
                for item in res:
                    orig = item.get('orig', '')
                    hira = item.get('hira', '')
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
        elif re.match(r'^[，。！？、?.,!/]+$', part):
            p = part.replace('！', '。').replace('!', '。').replace('，', '、').replace(',', '、').replace('.', '。')
            tokens.append(p)

    raw_koe = '/'.join(tokens)
    clean_koe = re.sub(r'[\s\t\r\n]+', '/', raw_koe)
    clean_koe = re.sub(r'[^\u3040-\u309f\u30a0-\u30ff、。？?ー/\']', '', clean_koe)
    clean_koe = re.sub(r'/+', '/', clean_koe)
    clean_koe = re.sub(r'/([、。？?])', r'\1', clean_koe)
    clean_koe = re.sub(r'([、。？?])/', r'\1', clean_koe)
    clean_koe = re.sub(r'、+', '、', clean_koe)
    clean_koe = re.sub(r'。+', '。', clean_koe)
    clean_koe = clean_koe.strip('/、')
    return clean_koe

# ==========================================
# 3. AquesTalk 合成与 PipeWire 异步推流
# ==========================================
class YukkuriPlayer:
    def __init__(self, target_sink: str = "yukkuri_sink", speed: int = 100, lang: str = "zh"):
        self.target_sink = target_sink
        self.speed = max(50, min(300, speed))
        self.lang = lang
        self.queue = queue.Queue()
        self.running = True
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()

    def enqueue(self, text: str):
        if text.strip():
            self.queue.put(text.strip())

    def _synthesize(self, koe: str):
        size = ctypes.c_int(0)
        encoded_data = koe.encode('utf-8', errors='ignore') if use_utf8 else koe.encode('shift-jis', errors='ignore')

        wav_ptr = aq_synthe_fn(encoded_data, self.speed, ctypes.byref(size))
        if not wav_ptr:
            err_code = size.value
            err_desc = AQUESTALK_ERROR_MAP.get(err_code, "未知错误")
            print(f"[合成错误] AquesTalk 错误码 {err_code}: {err_desc} (记号列: '{koe}')")
            return None

        wav_data = ctypes.string_at(wav_ptr, size.value)
        aq.AquesTalk_FreeWave(wav_ptr)
        return wav_data

    def _worker(self):
        while self.running:
            try:
                text = self.queue.get(timeout=0.2)
            except queue.Empty:
                continue

            try:
                koe = text_to_yukkuri_polyglot(text, current_lang=self.lang)
                if not koe:
                    continue

                print(f"\n[识别原文]: {text}")
                print(f"[油库里音标]: {koe}")

                wav_data = self._synthesize(koe)
                if not wav_data:
                    continue

                print(f"[推送音频]: {len(wav_data)} 字节 -> {self.target_sink}")

                cmd = ["pw-play"]
                if self.target_sink:
                    cmd.extend(["--target", self.target_sink])
                cmd.append("-")

                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE
                )
                _, stderr = proc.communicate(input=wav_data)
                if proc.returncode != 0 and stderr:
                    print(f"[播放警告] pw-play 提示: {stderr.decode(errors='ignore').strip()}")

            except Exception as e:
                print(f"[TTS 异常]: {e}", file=sys.stderr)
            finally:
                self.queue.task_done()

    def stop(self):
        self.running = False
        if self.worker_thread.is_alive():
            self.worker_thread.join(timeout=1.0)

# ==========================================
# 4. ASR 引擎实现 (SenseVoice 与 Vosk)
# ==========================================
def clean_sensevoice_text(text: str) -> str:
    """清理 SenseVoice 输出的情感与富文本标签"""
    clean = re.sub(r'<\|.*?\|>', '', text)
    return clean.strip()

def run_sensevoice_loop(args, player, stop_event):
    """SenseVoice + Silero-VAD 极速高精度多语种监听循环"""
    sensevoice_dir = os.path.join(script_dir, "sensevoice")
    if not os.path.exists(sensevoice_dir):
        sensevoice_dir = os.path.join(script_dir, "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17")

    model_file = os.path.join(sensevoice_dir, "model.int8.onnx")
    tokens_file = os.path.join(sensevoice_dir, "tokens.txt")
    vad_file = os.path.join(script_dir, "silero_vad.onnx")

    if not (os.path.exists(model_file) and os.path.exists(tokens_file) and os.path.exists(vad_file)):
        print("[错误] 未找到 SenseVoice 或 Silero VAD 模型，正在自动回退到 Vosk 引擎...")
        run_vosk_loop(args, player, stop_event)
        return

    print(">>> 正在初始化 SenseVoice-Small 识别引擎...")
    recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=model_file,
        tokens=tokens_file,
        num_threads=4,
        use_itn=True
    )

    print(">>> 正在加载 Silero-VAD 语音活动检测器...")
    vad_config = sherpa_onnx.VadModelConfig()
    vad_config.silero_vad.model = vad_file
    vad_config.silero_vad.min_silence_duration = 0.35  # 静音 350ms 自动断句
    vad_config.silero_vad.min_speech_duration = 0.15
    vad_config.silero_vad.threshold = 0.5
    vad_config.sample_rate = 16000
    vad = sherpa_onnx.VoiceActivityDetector(vad_config, buffer_size_in_seconds=30)

    audio_queue = queue.Queue()

    def mic_callback(indata, frames, time, status):
        if status:
            print(f"[麦克风状态]: {status}", file=sys.stderr)
        audio_queue.put(indata.flatten().copy())

    print("\n" + "=" * 65)
    print("  油库里实时语音转换器已就绪 [SenseVoice 高精度引擎]")
    print("  - 识别能力: 阿里通义 SenseVoice-Small (中/英/日自动识别)")
    print("  - 断句控制: Silero-VAD (350ms 灵敏断句)")
    print(f"  - 油库里语速: {args.speed}")
    print(f"  - 音频目标: {args.target}")
    if args.device is not None:
        print(f"  - 输入设备 ID: {args.device}")
    print("  - 提示: 请对着麦克风说话，按 Ctrl+C 可停止程序")
    print("=" * 65 + "\n")

    with sd.InputStream(
        samplerate=16000,
        channels=1,
        dtype='float32',
        blocksize=800,
        device=args.device,
        callback=mic_callback
    ):
        while not stop_event.is_set():
            try:
                samples = audio_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            vad.accept_waveform(samples)
            while not vad.empty():
                seg = vad.front
                vad.pop()
                if len(seg.samples) < 16000 * 0.2:
                    continue  # 忽略极短杂音 (<200ms)

                stream = recognizer.create_stream()
                stream.accept_waveform(16000, seg.samples)
                recognizer.decode_stream(stream)
                raw_text = stream.result.text
                text = clean_sensevoice_text(raw_text)
                if text:
                    player.enqueue(text)

def run_vosk_loop(args, player, stop_event):
    """经典 Vosk 识别监听循环"""
    mapping = {
        "zh": ["model_cn", "model"],
        "cn": ["model_cn", "model"],
        "ja": ["model_ja", "model"],
        "en": ["model_en", "model"]
    }
    candidates = mapping.get(args.lang.lower(), ["model"])
    model_path = args.model
    if not model_path:
        for c in candidates:
            p = os.path.join(script_dir, c)
            if os.path.exists(p):
                model_path = p
                break

    if not model_path or not os.path.exists(model_path):
        print(f"[严重错误] 未找到 Vosk 模型: {model_path}")
        sys.exit(1)

    print(f">>> 正在加载 Vosk 模型 ({model_path})...")
    model = Model(model_path)
    recognizer = KaldiRecognizer(model, 16000)

    def mic_callback(indata, frames, time, status):
        if status:
            print(f"[麦克风状态]: {status}", file=sys.stderr)
        if recognizer.AcceptWaveform(bytes(indata)):
            res = json.loads(recognizer.Result())
            text = res.get("text", "")
            if text:
                player.enqueue(text)

    print("\n" + "=" * 60)
    print("  油库里实时语音转换器已就绪 [Vosk 传统引擎]")
    print(f"  - 识别语种: {args.lang}")
    print(f"  - 油库里语速: {args.speed}")
    print(f"  - 输出目标: {args.target}")
    print("  - 提示: 请对着麦克风说话，按 Ctrl+C 可停止程序")
    print("=" * 60 + "\n")

    with sd.RawInputStream(
        samplerate=16000,
        blocksize=4000,
        dtype='int16',
        channels=1,
        device=args.device,
        callback=mic_callback
    ):
        while not stop_event.is_set():
            stop_event.wait(0.5)

# ==========================================
# 5. 主程序入口
# ==========================================
def main():
    parser = argparse.ArgumentParser(description="新一代实时语音转油库里音效虚拟麦克风工具")
    parser.add_argument("--engine", type=str, default="sensevoice", choices=["sensevoice", "vosk"],
                        help="ASR 识别引擎: sensevoice (阿里高精度端到端, 默认), vosk (传统轻量)")
    parser.add_argument("--lang", type=str, default="zh", choices=["zh", "cn", "ja", "en"],
                        help="识别与发音语种 (SenseVoice 自动支持多语种; Vosk 用于选择模型)")
    parser.add_argument("--model", type=str, default=None,
                        help="自定义模型路径")
    parser.add_argument("--target", type=str, default="yukkuri_sink",
                        help="PipeWire 目标 sink (默认: yukkuri_sink)")
    parser.add_argument("--speed", type=int, default=100,
                        help="油库里语速 50~300 (默认: 100)")
    parser.add_argument("--device", type=int, default=None,
                        help="麦克风设备索引 ID (默认使用系统默认)")
    parser.add_argument("--list-devices", action="store_true",
                        help="列出所有可用音频设备并退出")

    args = parser.parse_args()

    if args.list_devices:
        print("=== 可用音频设备列表 ===")
        print(sd.query_devices())
        return

    player = YukkuriPlayer(target_sink=args.target, speed=args.speed, lang=args.lang)

    stop_event = threading.Event()
    def sig_handler(sig, frame):
        stop_event.set()

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    try:
        if args.engine == "sensevoice" and HAS_SHERPA:
            run_sensevoice_loop(args, player, stop_event)
        else:
            run_vosk_loop(args, player, stop_event)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"[运行时异常]: {e}", file=sys.stderr)
    finally:
        print("\n>>> 正在停止油库里转换器...")
        player.stop()
        print(">>> 已安全退出。")

if __name__ == "__main__":
    main()
