from typing import Any, Generator
from openai import OpenAI
from llama_index.core.llms.callbacks import (
    llm_completion_callback,
)
from llama_index.core.llms import (
    CustomLLM,
    CompletionResponse,
    CompletionResponseGen,
    LLMMetadata,
)
from pydantic import Field, PrivateAttr


class MyLLM(CustomLLM):
    model_name: str
    system_prompt: str = ""
    default_kwargs: dict = Field(default_factory=dict)
    _client: Any = PrivateAttr()

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        system_prompt: str = "",
        **kwargs,
    ):
        # provider-specific params
        extra_body = kwargs.pop("extra_body", {})
        # default kwargs
        if "gpt-oss" in model.lower():
            default_kwargs = {
                "temperature": 0.0,
                # shutdown thinking for all providers
                "reasoning_effort": "low",
                "extra_body": {
                    **extra_body,
                },
                # allow user override
                **kwargs,
            }

        else:
            default_kwargs = {
                "temperature": 0.0,
                # shutdown thinking for all providers
                "extra_body": {
                    "chat_template_kwargs": {
                        "enable_thinking": False,
                    },
                    "enable_thinking": False,
                    "thinking": {
                        "type": "disabled",
                    },
                    # user extra params
                    **extra_body,
                },
                # allow user override
                **kwargs,
            }
        super().__init__(
            model_name=model,
            system_prompt=system_prompt,
            default_kwargs=default_kwargs,
        )
        self._client = OpenAI(base_url=base_url, api_key=api_key)

    @property
    def metadata(self) -> LLMMetadata:
        return LLMMetadata(
            model_name=self.model_name,
            context_window=8192,
            num_output=5120,
            is_chat_model=True,
        )

    @llm_completion_callback()
    def complete(
        self,
        prompt: str,
        response_format=None,
        **kwargs: Any,
    ) -> CompletionResponse:
        return self._complete(prompt, response_format, **kwargs)

    @llm_completion_callback()
    def stream_complete(
        self,
        prompt: str,
        **kwargs: Any,
    ) -> CompletionResponseGen:
        return self._stream_complete(prompt, **kwargs)

    def _build_messages(self, prompt: str):
        messages = []
        if self.system_prompt:
            messages.append(
                {
                    "role": "system",
                    "content": self.system_prompt,
                }
            )

        messages.append(
            {
                "role": "user",
                "content": prompt,
            }
        )
        return messages

    def _merge_kwargs(
        self,
        prompt: str,
        stream: bool,
        response_format=None,
        **kwargs,
    ):
        final_kwargs = {
            "model": self.model_name,
            "messages": self._build_messages(prompt),
            "stream": stream,
            **self.default_kwargs,
            **kwargs,
        }
        if response_format:
            final_kwargs["response_format"] = response_format
        if stream:
            final_kwargs.setdefault(
                "stream_options",
                {
                    "include_usage": True,
                },
            )

        return final_kwargs

    def _complete(
        self,
        prompt: str,
        response_format=None,
        **kwargs: Any,
    ) -> CompletionResponse:
        final_kwargs = self._merge_kwargs(
            prompt=prompt,
            stream=False,
            response_format=response_format,
            **kwargs,
        )
        response = self._client.chat.completions.create(**final_kwargs)
        text = response.choices[0].message.content or ""
        return CompletionResponse(text=text, raw=response)

    def _stream_complete(
        self,
        prompt: str,
        **kwargs: Any,
    ) -> CompletionResponseGen:
        final_kwargs = self._merge_kwargs(
            prompt=prompt,
            stream=True,
            **kwargs,
        )
        stream = self._client.chat.completions.create(**final_kwargs)

        def gen() -> Generator[CompletionResponse, None, None]:
            for chunk in stream:
                delta = ""
                try:
                    if chunk.choices:
                        delta = chunk.choices[0].delta.content or ""

                except Exception:
                    delta = ""

                yield CompletionResponse(
                    text=delta,
                    delta=delta,
                    raw=chunk,
                )

        return gen()
