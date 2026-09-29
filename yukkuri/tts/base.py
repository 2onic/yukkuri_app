"""
TTS 语音合成引擎抽象基类
"""

from abc import ABC, abstractmethod
from typing import Optional

class BaseTTSEngine(ABC):
    """TTS 语音合成接口"""

    @abstractmethod
    def synthesize(self, koe: str, speed: int = 100) -> Optional[bytes]:
        """
        合成音频
        :param koe: 油库里音标字符串 (例如: にー/はお)
        :param speed: 语速 (通常 50~300)
        :return: WAV 二进制音频字节流，失败则返回 None
        """
        pass

    def close(self):
        """释放资源"""
        pass
