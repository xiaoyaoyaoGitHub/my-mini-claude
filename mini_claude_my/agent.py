import anthropic
import time
import asyncio
from typing import Any
from pathlib import Path
import uuid

from .ui import print_error, print_assistant_prompt, start_spinner, stop_spinner,print_assistant_thinking,print_cost,print_tool_call,print_tool_result, print_info, print_subagent_start, print_subagent_end
from .tools import tool_definitions,check_permission, _execute_tool,record_permission_settings
from .prompt import build_system_prompt
from .session import save_session

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
            is_sub_agent: bool = False,
            custom_system_prompt: str | None = None

    ):
        self.permission_mode = permission_mode
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.thinking = thinking
        # 补充系统提示词 不然 subagent容易丢失规范
        self._base_system_prompt = build_system_prompt() + "\n\n" + (custom_system_prompt if custom_system_prompt is not None else "")
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
        self.effective_window = 200000 # 窗口预算
        # 标识子 agent
        self._sub_agent = is_sub_agent
        self._output_buffer:list[str] | None = [] if is_sub_agent else None # 记录子 agent 的结果
        # 工具 tools
        self.tools = tool_definitions
        # 创建 session_id
        self.session_id = uuid.uuid4().hex[:8]
        self.session_start_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # 设定思考模式
    def _resolve_thinking_mode(self):
        if not self.thinking:
            return "disabled"
        # todo 这里处理支持 thinking 的模型
        # todo 这里处理支持 自适应的模型 adaptive
        return "enabled"

    # 区分 subagent 与 agent subagent 要收集 不打印
    def _omit_text(self,text,fn) -> None:
        # print(f"_omit_text,{self._output_buffer}")
        if self._output_buffer is not None:
            self._output_buffer.append(text)
        else:
            fn(text)

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
                            self._omit_text(delta.text,print_assistant_prompt)
                        # 思考增量
                        elif getattr(delta, 'type') == 'thinking_delta':
                            if first_text:
                                stop_spinner()
                                print_assistant_prompt("\n [thinking...]")
                                # self._omit_text('\n [thinking...]', print_assistant_prompt)
                                first_text = False
                            # 思考的内容可以不用subagent可以不用收集
                            # self._omit_text(delta.thinking,print_assistant_thinking)
                            print_assistant_thinking(delta.thinking)
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
                            # tb:{'id': 'tool_9adfa024869046df8f0687f6', 'name': 'list_files', 'input_json': '{"pattern": "*"}'}
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

    # 执行 skill 调用
    async def _execute_skill(self, block) -> str:
       try:
           inp = block["input"]
           from .skills import execute_skill
           result = execute_skill(inp)
           if not result:
               return f"Unknown skill: {inp.get('skill_name', '')}"
           # 如果不需要开启子进程 直接返回提示回灌 主 agent 自己照着做
           if result["context"] == "inline":
               return result["prompt"]
           # 开始创建subagent
           print_subagent_start("skill", inp.get("skill_name", ''))
           sub_agent = Agent(
                api_key=self.api_key,
                base_url=self.base_url,
                permission_mode=self.permission_mode,
                model=self.model,
                is_sub_agent=True,
                custom_system_prompt = result["prompt"]
            )
           # 剔除subagent中 skill 的 tool 防止无限套娃
           sub_agent.tools = [ tool for tool in sub_agent.tools if tool["name"] != "skill"  ]
           await sub_agent.chat(inp.get("args") or "Execute this skill task.")
           text = "".join(sub_agent._output_buffer)
           # print(f"sub_result:{''.join(sub_agent._output_buffer)}")
           # print(f"发送后：{sub_agent.total_input_tokens},{sub_agent.total_output_tokens}" )
           # 将 token累加到主 agent 中
           self.total_input_tokens += sub_agent.total_input_tokens
           self.total_output_tokens += sub_agent.total_output_tokens
           # subagent结束
           print_subagent_end("skill", inp.get("skill_name", ''))
           return text or "(Skill produced no output)"
       except Exception as e:
           print(f"execute skill :{e}")
           return f"Skill execution failed: {e}"

    # 工具分流执行 如果是 skill 需要开辟一个 subagent 执行
    async def _execute_tool_call(self, tool_block) -> str:
        tool_name = tool_block['name']
        if tool_name == "skill":
            # TODO 工具调用执行结果
            return await self._execute_skill(tool_block)
        else:
            # 都是工具
           return await _execute_tool(tool_block)

    # 检测工具返回结果是否长
    def _check_large_result(self,tool_name:str,result:str) -> str:
        THRESHOLD = 80 * 1024 # 阈值
        if len(result.encode()) <= THRESHOLD:
            return result
        # 设置保存工具结果
        tool_result_path = Path.cwd() / ".my_claude" / "tools_results"
        # 创建目录
        tool_result_path.mkdir(parents=True, exist_ok=True)
        filename = f"{int(time.time() * 1000)}-{tool_name}.txt"
        file_path = tool_result_path / filename
        file_path.write_text(result, encoding="utf-8")
        file_size = len(result.encode()) / 1024

        return (
            f"[Result too large ({file_size:.1f} KB). "
            f"Full output saved to {file_path}. "
            f"You can use read_file to see the full result.]\n\n"
        )

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

            # 开始 thinking 动画
            if not self._sub_agent:
                start_spinner()

            # 计算上下文窗口剩余额度 是否需要压缩上下文
            await self.check_compact()
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
                    task = asyncio.create_task(self._execute_tool_call(tool_block))
                    # 并将 task 保存到 early_executions中
                    early_executions[tool_block['id']] = task

            response = await self._call_anthropic_stream(on_tool_block_complete=_on_tool_block)
            if not response:
                break
            # print(f"\n response: {response}")
            # 记录输入输出 token 及时间
            self.last_api_call_time = time.time()
            # 当前对话上下文大小的最准确的测量值
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
                if not self._sub_agent:
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
                        # print(f"{tu.name},{perm['message']}")
                        allow_result = input("  Allow? (y/n): ")
                        print(f"allow result: {allow_result}")
                        # 用户拒绝
                        if not allow_result.lower().startswith("y"):
                            tool_results.append({"type":"tool_result","tool_use_id":tu.id, "content":"User denied this action."})
                            continue
                        result = await self._execute_tool_call({"name": tu.name, "input": inp})
                        # 把当前权限内容添加到project_settings
                        record_permission_settings(tu.name, perm["message"])
                    # 被拒绝
                    if perm["action"] == "deny":
                        tool_results.append({"type":"tool_result","tool_use_id":tu.id, "content":"Denied by permission rules."})
                        continue
                # todo 如果工具结果调用太长，写入到本地文件中 防止上下文暴增
                result = self._check_large_result(tu.name,result)
                print_tool_result(tu.name, result)
                tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": result})
            self.current_turns += 1
            # subagent不触发
            if not self._sub_agent:
                stop_spinner()
            # 如果工具有返回结果，需要最后添加到 messages，不然下一轮对话大模型认为调用工具没有收到回复
            if tool_results:
                self._anthropic_messages.append({
                    "role":"user",
                    "content": tool_results
                })

        # 保存会话
        if not self._sub_agent:
            self._auto_save()


    # 恢复会话
    def restore_session(self, data:dict) -> None:
        self._anthropic_messages = data["anthropicMessages"]
        self.session_id = data["metadata"]["id"]
    # 自动保存
    def _auto_save(self) -> None:
        save_session(self.session_id,{
            "metadata":{
                "id":self.session_id,
                "model":self.model,
                "cwd":str(Path.cwd()),
                "startTime":self.session_start_time,
                "messageCount":len(self._anthropic_messages)
            },
            "anthropicMessages": self._anthropic_messages
        })
    # 检测压缩上下文
    async def check_compact(self):
        if self.last_input_tokens >= self.effective_window * 0.8:
            print_info("Context window filling up, compacting conversation...")
            await self.compact()

    # 压缩会话
    async def compact(self) -> None:
       if await self._anthropic_compact():
            print_info("Conversation compacted.")

    # anthropic compact
    async def _anthropic_compact(self) -> None | bool:
       try:
           # print(f"_anthropic_message", self._anthropic_messages)
           # 取最后一条用户信息
           last_user_message = self._anthropic_messages[-1]
           # print_info(f"Last user message: {last_user_message['content']}")
           keep_last = self.is_plain_user_message(last_user_message)
           to_summary = self._anthropic_messages[:-1] if keep_last else self._anthropic_messages
           # 创建大模型对话，将除最后一条的信息都发给大模型进行总结
           start_spinner()
           summary_result = await self._anthropic_client.messages.create(
               model=self.model,
               max_tokens=2048,
               tools=self.tools,
               system="You are a conversation summarizer. Be concise but preserve important details.",
               messages=[
                   *to_summary,
                   {"role": "user",
                    "content": "Summarize the conversation so far in a concise paragraph, preserving key decisions, file paths, and context needed to continue the work."},
               ]
           )
           stop_spinner()
           summary_text = 'No summary available.'
           for summary in summary_result.content:
               if summary.type == 'text':
                   summary_text = summary.text
           print_info(f"Summary text: {summary_text}")
           self._anthropic_messages = [
               {"role": "user", "content": f"[Previous conversation summary]\n{summary_text}"},
               {"role": "assistant",
                "content": "Understood. I have the context from our previous conversation. How can I continue helping?"},
           ]
           if keep_last:
               self._anthropic_messages.append(last_user_message)
           else:
               # 如果是任务途中 补充一条指令继续执行
               self._anthropic_messages.append({
                   "role": "user",
                   "content": "Continue the task described in the summary."
               })
           self.last_input_tokens = 0
       except Exception as e:
           print_error(f"压缩错误:{e}")
           return False

    # 判断是普通的用户信息
    @staticmethod
    def is_plain_user_message(message) -> bool:
        """ 根据信息内容判断是否为普通的用户信息 """
        if message["role"] != "user":
            return False
        content = message['content']
        if isinstance(content, str):
            return True
        _is_plain = True
        # for c in content:
        #     if c.get("type") == 'tool_result':
        #         _is_plain = False
        #         break
        # return _is_plain
        # 简写版
        return not any(c.get("type") == "tool_result" for c in content)

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

