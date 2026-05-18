import base64
import mimetypes
from pathlib import Path

from openai import OpenAI


class VisionClient:
    def __init__(
        self,
        api_base: str,
        api_key: str,
        model: str,
        timeout: int = 120,
    ):
        self.model = model
        self.client = OpenAI(
            api_key=api_key,
            base_url=api_base,
            timeout=timeout,
        )

    def analyze_image(
        self,
        image_path: Path,
        prompt: str,
    ) -> str:
        image_base64 = self._encode_image(image_path)
        mime_type = mimetypes.guess_type(image_path)[0] or "image/png"
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt,
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": (f"data:{mime_type};base64,{image_base64}")
                            },
                        },
                    ],
                }
            ],
            extra_body={
                "chat_template_kwargs": {
                    "enable_thinking": False,
                },
                "enable_thinking": False,
                "thinking": {
                    "type": "disabled",
                },
            },
            max_tokens=4096,
            temperature=0.1,
            top_p=0.8,
        )
        model_name = None
        content = response.choices[0].message.content
        model_name = response.model
        return (content or "").strip(), model_name

    def _encode_image(
        self,
        image_path: Path,
    ) -> str:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
