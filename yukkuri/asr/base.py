"""
ASR 语音识别引擎抽象基类
"""

from abc import ABC, abstractmethod
import numpy as np

class BaseASREngine(ABC):
    """ASR 识别接口基类"""

    @abstractmethod
    def decode(self, samples: np.ndarray, sample_rate: int = 16000) -> str:
        """
        解码语音切片为文本
        :param samples: float32 一维音频数组
        :param sample_rate: 采样率
        :return: 识别出的纯文本
        """
        pass

    def close(self):
        """释放资源"""
        pass
