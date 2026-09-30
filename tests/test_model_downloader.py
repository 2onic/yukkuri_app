"""
语音模型下载管理器与解压逻辑单元测试
"""

import os
import io
import tarfile
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from yukkuri.config import AppConfig
from yukkuri.model_downloader import (
    check_model_status,
    download_sensevoice,
)

class TestModelDownloader(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_sensevoice_int8_dir_detection(self):
        """测试 config 与 model_downloader 识别 int8 官方模型目录"""
        root = self.tmp_dir.name
        int8_dir = os.path.join(root, "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17")
        os.makedirs(int8_dir, exist_ok=True)
        with open(os.path.join(int8_dir, "model.int8.onnx"), "wb") as f:
            f.write(b"dummy_model")
        with open(os.path.join(int8_dir, "tokens.txt"), "w") as f:
            f.write("dummy_tokens")

        cfg = AppConfig(project_root=root)
        self.assertEqual(cfg.find_sensevoice_dir(), os.path.abspath(int8_dir))

        status = check_model_status(root=root)
        self.assertTrue(status["sensevoice"])

    def test_download_sensevoice_extracts_and_excludes_unquantized(self):
        """测试 download_sensevoice 能够正确解压并剔除冗余的未量化 model.onnx"""
        root = self.tmp_dir.name
        archive_path = os.path.join(root, "sensevoice.tar.bz2")
        dir_name = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"

        # 构建一个模拟的 tar.bz2 归档
        with tarfile.open(archive_path, "w:bz2") as tar:
            for fname, content in [
                (f"{dir_name}/model.int8.onnx", b"int8_model_content"),
                (f"{dir_name}/tokens.txt", b"tokens_content"),
                (f"{dir_name}/model.onnx", b"900MB_unquantized_content"),
            ]:
                data = io.BytesIO(content)
                ti = tarfile.TarInfo(name=fname)
                ti.size = len(content)
                tar.addfile(ti, data)

        with patch("yukkuri.model_downloader.download_file") as mock_dl:
            res_dir = download_sensevoice(root=root)
            # 因为本地已有压缩包，无需重复发起网络下载
            mock_dl.assert_not_called()

        extracted_dir = os.path.join(root, dir_name)
        # model.int8.onnx 与 tokens.txt 应该存在
        self.assertTrue(os.path.exists(os.path.join(extracted_dir, "model.int8.onnx")))
        self.assertTrue(os.path.exists(os.path.join(extracted_dir, "tokens.txt")))
        # model.onnx 应该被删除或排除
        self.assertFalse(os.path.exists(os.path.join(extracted_dir, "model.onnx")))
        # sensevoice 软链接应成功建立
        self.assertTrue(os.path.exists(os.path.join(root, "sensevoice")))

    def test_install_aquestalk_single_dll(self):
        """测试直接导入单个 AquesTalk.dll"""
        from yukkuri.model_downloader import install_aquestalk_from_archive
        root = self.tmp_dir.name
        dummy_dll = os.path.join(root, "AquesTalk.dll")
        with open(dummy_dll, "wb") as f:
            f.write(b"dummy dll content")

        with patch("sys.platform", "win32"):
            voices = install_aquestalk_from_archive(dummy_dll, root=root)
            self.assertIn("f1", voices)
            # 确认拷贝到了 libs/aquestalk
            self.assertTrue(os.path.exists(os.path.join(root, "libs", "aquestalk", "AquesTalk.dll")))

    def test_install_aquestalk_zip_dll(self):
        """测试从 zip 压缩包中解压 AquesTalk.dll 或声线 dll"""
        import zipfile
        from yukkuri.model_downloader import install_aquestalk_from_archive
        root = self.tmp_dir.name
        zip_path = os.path.join(root, "aqtk1-win.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("aqtk1-win/AquesTalk.dll", b"fake dll")
            zf.writestr("aqtk1-win/lib64/f2/AquesTalk.dll", b"fake f2 dll")

        with patch("sys.platform", "win32"):
            voices = install_aquestalk_from_archive(zip_path, root=root)
            self.assertIn("f1", voices)
            self.assertIn("f2", voices)

if __name__ == "__main__":
    unittest.main()
