import anthropic
import time
from typing import Any

from .ui import print_error, print_assistant_prompt, start_spinner, stop_spinner,print_assistant_thinking,print_cost


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
        # 创建 anthropic 消息 list 后续可以对对话进行压缩
        self._anthropic_messages: list[dict] = []
        # 创建 anthropic 异步客户端
        self._anthropic_client = anthropic.AsyncAnthropic(api_key=self.api_key, base_url=self.base_url)
        # 花费
        self.last_api_call_time = 0.0 
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.last_input_tokens = 0
        self.current_turns = 0 # 记录轮次

    # 发送 anthropic_message_stream
    async def _call_anthropic_stream(self):

        """
        *...: 把切片结果解包成位置参数/列表元素
        ...[:-1]: 切片，取除了最后一个元素之外的所有元素， list[a:b] 取 [a, b) 区间；省略 a 表示从头，省略 b 表示到尾。负数索引从末尾数，-1 是最后一个元素的位置
        """
        # 流式传输
        create_params: dict[str, Any] = {
            "max_tokens": 1024,
            "model": self.model,
            "messages": self._anthropic_messages,
            "thinking":{
                "type":"enabled",
                "budget_token": 10000,
                "display":"omitted"
            }
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
            # 开始 thinking 动画
            start_spinner()
            # 首字输出
            first_text = True
            # 发送请求
            async with self._anthropic_client.messages.stream(**create_params) as stream:
                async for event in stream:
                    """
                    一系列内容块，每个内容块都有一个 content_block_start、
                    一个或多个 content_block_delta 事件以及一个 content_block_stop 事件。
                    每个内容块都有一个 index，对应于其在最终 Message content 数组中的索引。
                    有一个例外：在服务器端回退响应期间，fallback 内容块会在每个模型边界处以一对 content_block_start 和 content_block_stop 的形式到达，中间没有任何增量
                    """
                    if getattr(event, 'type') == 'content_block_start':
                        pass
                    # delta 增量
                    if getattr(event, 'type') == 'content_block_delta':
                        # 内容块增量
                        delta = event.delta

                        # 文本增量
                        if getattr(delta, 'type') == 'text_delta':
                            if first_text:
                                stop_spinner()
                                print('\n', end="", flush=True)
                                first_text = False
                            # 最终的内容在此处打印
                            print_assistant_prompt(delta.text)
                        # 思考增量
                        elif getattr(delta, 'type') == 'thinking_delta':
                            if first_text:
                                stop_spinner()
                                print_assistant_prompt('\n [thinking...]')
                                first_text = False
                            # print_assistant_thinking(delta.thinking)
                        # json增量
                        elif getattr(delta, 'type') == 'input_json_delta':
                            # TODO json 增量
                            pass
                    if getattr(event, 'type') == 'content_block_stop':
                        pass
                final_messages = await stream.get_final_message()
                # print(f"final_messages: {final_messages}")
                final_messages.content = [c for c in final_messages.content if c.type != 'thinking']
                # 将除 thinking 内容解析出来 返回给
                return final_messages
        except Exception as error:
            print(f"error: {error}")
            body = error.body or {}
            err = body.get('error', {})
            msg = err.get('message', '')
            code = err.get('code', '')  # 代理经常空字符串
            etype = err.get('type', '')  # 'new_api_error' 等
            print_error(f'{etype}/{code}: {msg}')
            return None

    # agent 发送 messages
    async def chat(self, user_messages):
        # 将用户信息塞入信息 list
        # self._anthropic_messages.append({
        #     "role": "user",
        #     "content": user_messages
        # })
        self._anthropic_messages = [{
            "role": "user",
            "content": user_messages
        }]
        response = await self._call_anthropic_stream()
        print(f"\n response: {response}")
        # 记录输入输出 token 及时间
        self.last_api_call_time = time.time()
        self.last_input_tokens = response.usage.input_tokens
        self.total_input_tokens += response.usage.input_tokens
        self.total_output_tokens += response.usage.output_tokens
        print_cost(self.total_input_tokens, self.total_output_tokens)
        self.current_turns += 1

        stop_spinner()
        def _block_to_dict(block):
            if block.type == 'text':
                return {"type": "text", "content": block.text}
            else:
                return {"type": block.type}
        self._anthropic_messages.append({
            "role": "assistant",
            "content": [_block_to_dict(c) for c in response.content]
        })


