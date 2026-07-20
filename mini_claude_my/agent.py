import anthropic
import time
import asyncio
from typing import Any

from .ui import print_error, print_assistant_prompt, start_spinner, stop_spinner,print_assistant_thinking,print_cost,print_tool_call,print_tool_result
from .tools import tool_definitions,CONCURRENCY_SAFE_TOOLS,check_permission, _execute_tool,record_permission_settings
from .prompt import build_system_prompt

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
        self._base_system_prompt = build_system_prompt()
        # 设置思考模式
        self._thinking_mode = self._resolve_thinking_mode()
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

        # 工具 tools
        self.tools = tool_definitions

    # 设定思考模式
    def _resolve_thinking_mode(self):
        if not self.thinking:
            return "disabled"
        # todo 这里处理支持 thinking 的模型
        # todo 这里处理支持 自适应的模型 adaptive
        return "enabled"

    # 发送 anthropic_message_stream
    async def _call_anthropic_stream(self,on_tool_block_complete=None):

        """
        *...: 把切片结果解包成位置参数/列表元素
        ...[:-1]: 切片，取除了最后一个元素之外的所有元素， list[a:b] 取 [a, b) 区间；省略 a 表示从头，省略 b 表示到尾。负数索引从末尾数，-1 是最后一个元素的位置
        """
        # 流式传输
        create_params: dict[str, Any] = {
            "max_tokens": 1024,
            "model": self.model,
            "messages": self._anthropic_messages,
            "tools": self.tools,
            "system": self._base_system_prompt,

        }
        if self._thinking_mode in ('adaptive', 'enabled'):
            create_params['thinking'] = {
                "type":"enabled",
                "budget_tokens": 16348,
                "display": "omitted"
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
            first_answer = True

            # 工具块记录
            tool_blocks_by_index: dict[int, dict[str, Any]] = {}

            # 发送请求
            async with self._anthropic_client.messages.stream(**create_params) as stream:
                async for event in stream:
                    """
                    一系列内容块，每个内容块都有一个 content_block_start、
                    一个或多个 content_block_delta 事件以及一个 content_block_stop 事件。
                    每个内容块都有一个 index，对应于其在最终 Message content 数组中的索引。
                    有一个例外：在服务器端回退响应期间，fallback 内容块会在每个模型边界处以一对 content_block_start 和 content_block_stop 的形式到达，中间没有任何增量
                    """
                    # print(f"\n {event}", end="", flush=True)
                    if getattr(event, 'type') == 'content_block_start':
                        """
                        数据格式： 
                        RawContentBlockStartEvent(
                            content_block=ToolUseBlock(
                                id='toolu_015796266d104da69c40d0a3', 
                                caller=None, 
                                input={}, 
                                name='list_files', 
                                type='tool_use'
                            ), 
                            index=1, 
                            type='content_block_start'
                        )
                        """
                        cb = getattr(event, 'content_block')
                        if cb.type == 'tool_use':
                            # 根据 event id 记录需调用的工具
                            tool_blocks_by_index[event.index] = {
                                "id":cb.id,
                                "name": cb.name,
                                "input_json":""
                            }

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
                            if first_answer:
                                print('\n', end="", flush=True)
                                first_answer = False
                            # 最终的内容在此处打印
                            print_assistant_prompt(delta.text)
                        # 思考增量
                        elif getattr(delta, 'type') == 'thinking_delta':
                            if first_text:
                                stop_spinner()
                                print_assistant_thinking('\n [thinking...]')
                                first_text = False
                            # print_assistant_thinking(delta.thinking)
                        # json增量
                        elif getattr(delta, 'type') == 'input_json_delta':
                            # 收集 tool 入参
                            tb = tool_blocks_by_index.get(event.index)
                            if hasattr(delta, 'partial_json'):
                                tb["input_json"] += delta.partial_json
                    if getattr(event, 'type') == 'content_block_stop':
                        # 开始调用工具
                        # 删除指定的键并返回它对应的值
                        tb = tool_blocks_by_index.pop(event.index,None)
                        # todo 处理工具调用
                        if tb and on_tool_block_complete:
                            import json as _json
                            try:
                                # 把 json 对象转化成 python 对象
                                parsed =  _json.loads(tb['input_json'] or "{}")
                            except Exception:
                                parsed = {}
                            #  parsed: {'pattern': '*'}
                            # tb:{'id': 'toolu_9adfa024869046df8f0687f6', 'name': 'list_files', 'input_json': '{"pattern": "*"}'}
                            # print(f"\n parsed: {parsed}, tb:{tb}", end="", flush=True)
                            on_tool_block_complete({
                                "type":"tool_use",
                                "id": tb['id'],
                                "name":tb['name'],
                                "input":parsed,
                            })
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
        self._anthropic_messages.append({
            "role": "user",
            "content": user_messages
        })
        # 如果不使用工具 可以不需要该循环，如果使用到了工具，需要将工具结果再次添加到 messages中
        # 询问大模型 直到给出结果
        while True:
            # 保存需要执行的工具
            early_executions:dict[str, asyncio.Task] = {}
            # print(f"_anthropic_messages: {len(self._anthropic_messages)}")
            """
                {
                    "type":"tool_use",
                    "id": tb['id'],
                    "name":tb['name'],
                    "input":parsed,
                }
            """
            def _on_tool_block(tool_block:dict[str, Any]) -> None:
                # 权限校验
                prem = check_permission(tool_block["name"], tool_block['input'], self.permission_mode)
                if prem['action'] == "allow":
                    # 创建 task 每个 task 中触发工具调用执行
                    task = asyncio.create_task(_execute_tool(tool_block))
                    # 并将 task 保存到 early_executions中
                    early_executions[tool_block['id']] = task

            response = await self._call_anthropic_stream(on_tool_block_complete=_on_tool_block)
            if not response:
                break
            # print(f"\n response: {response}")
            # 记录输入输出 token 及时间
            self.last_api_call_time = time.time()
            self.last_input_tokens = response.usage.input_tokens
            self.total_input_tokens += response.usage.input_tokens
            self.total_output_tokens += response.usage.output_tokens
            self._anthropic_messages.append({
                "role": "assistant",
                "content": [self._block_to_dict(c) for c in response.content]
            })
            # 如果是工具调用，则需要将工具结果添加到信息中 再次执行一轮对话再次返回
            tool_uses = [ t for t in response.content if t.type == 'tool_use']
            # 如果没有工具调用 打印总体的花费 并中断循环
            if not tool_uses:
                print_cost(self.total_input_tokens, self.total_output_tokens)
                break
            # 执行工具
            tool_results:list[dict] = []
            for tu in tool_uses:
                """
                    ToolUseBlock(
                        id='toolu_54da5a2d6bcb4c1fbeff9381', 
                        caller=None, 
                        input={'pattern': '*'}, 
                        name='list_files', 
                        type='tool_use'
                    )
                """
                inp = dict(tu.input)
                print_tool_call(tu.name, inp)
                # 开始获取工具调用结果
                tool_task = early_executions.get(tu.id)
                result = ''
                if tool_task:
                    result = await tool_task
                else:
                    # 如果没有 检查下权限
                    perm = check_permission(tu.name, tu.input, self.permission_mode)
                    # 需要确认
                    if perm["action"] == "confirm":
                        print(f"{tu.name},{perm['message']}")
                        result = input("  Allow? (y/n): ")
                        print(f"allow result: {result}")
                        # 用户拒绝
                        if not result.lower().startswith("y"):
                            tool_results.append({"type":"tool_result","tool_use_id":tu.id, "content":"User denied this action."})
                            continue
                        result = await _execute_tool({"name": tu.name, "input": inp})
                        # 把当前权限内容添加到project_settings
                        record_permission_settings(tu.name, perm["message"])
                print_tool_result(tu.name, result)
                tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": result})
            self.current_turns += 1
            stop_spinner()
            # 如果工具有返回结果，需要最后添加到 messages，不然下一轮对话大模型认为调用工具没有收到回复
            if tool_results:
                self._anthropic_messages.append({
                    "role":"user",
                    "content": tool_results
                })

    @staticmethod # 放到类命名空间的普通函数，不需要访问实例 self 或者 类 cls
    def _block_to_dict(block) -> dict:
        """ 记录大模型返回的信息 """
        if block.type == 'text':
            return {"type": "text", "text": block.text}
        elif block.type == 'tool_use':
            """
                ToolUseBlock(
                    id='toolu_54da5a2d6bcb4c1fbeff9381', 
                    caller=None, 
                    input={'pattern': '*'}, 
                    name='list_files', 
                    type='tool_use'
                )
            """
            return {"type":"tool_use","id":block.id,"name":block.name,"input":block.input}
        else:
            return {"type": block.type}

