import base64
import io
import os
from typing import Literal

from pydantic import BaseModel
from PIL import Image

ImageTypes = Literal["jpg", "jpeg", "png", "gif", "webp"]


class ImageData(BaseModel):
    """图像数据类

    Args:
        data (str): 图像数据（base64 编码）
        type (ImageTypes): 图像扩展名
    """

    data: str
    type: ImageTypes

    @staticmethod
    def _normalize_type(type_name: str) -> ImageTypes:
        normalized = type_name.lower().lstrip(".")
        if normalized in {"jpg", "jpeg", "png", "gif", "webp"}:
            return normalized  # type: ignore[return-value]
        raise ValueError(f"Unsupported image type: {type_name}")

    @property
    def media_type(self) -> str:
        # Some providers reject image/jpg and only accept image/jpeg.
        return "jpeg" if self.type == "jpg" else self.type

    @property
    def pil_format(self) -> str:
        return {
            "jpg": "JPEG",
            "jpeg": "JPEG",
            "png": "PNG",
            "gif": "GIF",
            "webp": "WEBP",
        }[self.type]

    @classmethod
    def load_from_file(cls, file_path: str) -> "ImageData":
        """从文件读取图像数据

        Args:
            file_path (str): 图像文件路径

        Returns:
            ImageData: 图像数据
        """
        with open(file_path, "rb") as f:
            raw_bytes = f.read()

        detected_type: str | None = None
        try:
            with Image.open(io.BytesIO(raw_bytes)) as image:
                if image.format:
                    detected_type = image.format.lower()
        except Exception:
            detected_type = None

        if detected_type is None:
            detected_type = os.path.splitext(file_path)[1][1:]

        normalized_type = cls._normalize_type(detected_type)
        data = base64.b64encode(raw_bytes).decode("utf-8")
        return cls(data=data, type=normalized_type)

    def merge(self, other: "ImageData") -> "ImageData":
        """合并两张图像数据

        Args:
            other (ImageData): 需要合并的图像数据

        Returns:
            ImageData: 合并后的图像数据
        """
        img1 = Image.open(io.BytesIO(base64.b64decode(self.data)))
        img2 = Image.open(io.BytesIO(base64.b64decode(other.data)))
        dst = Image.new("RGB", (img1.width + img2.width, img1.height))
        dst.paste(img1, (0, 0))
        dst.paste(img2, (img1.width, 0))
        output = io.BytesIO()
        dst.save(output, format=self.pil_format)
        return ImageData(data=base64.b64encode(output.getvalue()).decode("utf-8"), type=self.type)

    def convert(self, type: ImageTypes) -> "ImageData":
        """将图像数据转换为指定格式

        Args:
            type (ImageTypes): 目标格式
        """
        img = Image.open(io.BytesIO(base64.b64decode(self.data)))
        output = io.BytesIO()
        normalized_type = self._normalize_type(type)
        pil_format = {
            "jpg": "JPEG",
            "jpeg": "JPEG",
            "png": "PNG",
            "gif": "GIF",
            "webp": "WEBP",
        }[normalized_type]
        img.save(output, format=pil_format)
        return ImageData(data=base64.b64encode(output.getvalue()).decode("utf-8"), type=normalized_type)
