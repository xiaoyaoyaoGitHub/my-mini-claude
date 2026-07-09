import anthropic
import time
from typing import Any

from .ui import print_error,print_assistant_prompt,start_spinner

class Agent:
    # * 是 Python 3 的"关键字参数分界符"：
    # 它之后的所有参数必须以关键字形式传递，不能用位置传。
    """
        model  :  str | None  =  None
           ↑        ↑              ↑
         参数名   类型注解        默认值
    """
    def __init__(
            self,
            *,
            permission_mode: str | None = None,
            model: str | None = None,
            base_url: str | None = None,
            api_key: str | None = None,
            thinking: bool = False,

    ):
        self.permission_mode = permission_mode
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.thinking = thinking
        # 创建 anthropic 消息 list
        self._anthropic_messages: list[dict] = []
        # 创建 anthropic 异步客户端
        self._anthropic_client = anthropic.AsyncAnthropic(api_key=self.api_key, base_url=self.base_url)

    # agent 发送 messages
    async def chat(self, user_messages):
        self._anthropic_messages.append({
            "role":"user",
            "content":user_messages
        })
        """
        *...: 把切片结果解包成位置参数/列表元素
        ...[:-1]: 切片，取除了最后一个元素之外的所有元素， list[a:b] 取 [a, b) 区间；省略 a 表示从头，省略 b 表示到尾。负数索引从末尾数，-1 是最后一个元素的位置
        """
        # 流式传输
        create_params: dict[str, Any] = {
            "max_tokens":2048,
            "model": self.model,
            "messages": self._anthropic_messages,
        }
        """
        async with ... as stream: —— 异步上下文管理器
          - stream() 返回的对象实现了 __aenter__ / __aexit__，是异步上下文管理器
          - 进入 with 块时发请求、开流；退出时自动关流、释放连接
          - 即使中间抛异常或被取消（asyncio.CancelledError），__aexit__ 也会跑，避免连接泄漏
          - 对比同步版 with client.messages.stream(...) as stream: —— 加 async 表示进入/退出要走异步
          
        async for text in stream.text_stream —— 异步迭代文本块
          - stream.text_stream 是个异步迭代器，每来一段文本就 yield 一次
          - 每次 text 是几个 token 的字符串片段（不是字符级，也不是整段），例如 'Hello' → ', ' → 'world' → '!'
          - async for 等待下一段时会让出事件循环，期间其他协程可以跑（并发处理别的请求、UI 响应等）
          - 还有 stream_events 能拿到更细的事件（message_start / content_block_delta / message_stop 等），text_stream 是它的"只要文本"的便捷包装
        """
        try:
            start_spinner()
            time.sleep(1000)
            async with self._anthropic_client.messages.stream(**create_params) as stream:
                async for event in stream:
                    # end = '' 结尾不加换行
                    # flush=True 立刻重刷 stdout缓冲 不然看不到打字效果
                    if getattr(event,'type') == 'content_block_delta':
                        delta = event.delta
                        if hasattr(delta, 'thinking'):
                            print_assistant_prompt(delta.thinking)
                messages = await stream.get_final_message()
                # 将除 thinking 内容解析出来 返回给
                print(messages.to_json())
                return messages
        except Exception as error:
            body = error.body or {}
            err = body.get('error', {})
            msg = err.get('message', '')
            code = err.get('code', '')  # 代理经常空字符串
            etype = err.get('type', '')  # 'new_api_error' 等
            print_error(f'{etype}/{code}: {msg}')
