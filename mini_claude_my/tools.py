from pathlib import Path
import os
import json
import difflib
# 并发安全的工具 可以并行执行(只读 无副作用)
CONCURRENCY_SAFE_TOOLS = {"read_file","list_files","grep_search","web_search"}

# ─── Tool definitions ───────────────────────────────────────

tool_definitions: list[dict] = [
    {
        "name": "read_file",
        "description": "Read the contents of a file. Returns the file content with line numbers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "The path to the file to read"},
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file. Creates the file if it doesn't exist, overwrites if it does.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "The path to the file to write"},
                "content": {"type": "string", "description": "The content to write to the file"},
            },
            "required": ["file_path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Edit a file by replacing an exact string match with new content. The old_string must match exactly (including whitespace and indentation).",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "The path to the file to edit"},
                "old_string": {"type": "string", "description": "The exact string to find and replace"},
                "new_string": {"type": "string", "description": "The string to replace it with"},
            },
            "required": ["file_path", "old_string", "new_string"],
        },
    },
    {
        "name": "list_files",
        "description": "List files matching a glob pattern. Returns matching file paths.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": 'Glob pattern to match files (e.g., "**/*.ts", "src/**/*")'},
                "path": {"type": "string", "description": "Base directory to search from. Defaults to current directory."},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "grep_search",
        "description": "Search for a pattern in files. Returns matching lines with file paths and line numbers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "The regex pattern to search for"},
                "path": {"type": "string", "description": "Directory or file to search in. Defaults to current directory."},
                "include": {"type": "string", "description": 'File glob pattern to include (e.g., "*.ts", "*.py")'},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "run_shell",
        "description": "Execute a shell command and return its output. Use this for running tests, installing packages, git operations, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to execute"},
                "timeout": {"type": "number", "description": "Timeout in milliseconds (default: 30000)"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "skill",
        "description": "Invoke a registered skill by name. Skills are prompt templates loaded from .claude/skills/. Returns the skill's resolved prompt to follow.",
        "input_schema": {
            "type": "object",
            "properties": {
                "skill_name": {"type": "string", "description": "The name of the skill to invoke"},
                "args": {"type": "string", "description": "Optional arguments to pass to the skill"},
            },
            "required": ["skill_name"],
        },
    },
    {
        "name": "web_fetch",
        "description": "Fetch a URL and return its content as text. For HTML pages, tags are stripped to return readable text. For JSON/text responses, content is returned directly.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to fetch"},
                "max_length": {"type": "number", "description": "Maximum content length in characters (default 50000)"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "enter_plan_mode",
        "description": "Enter plan mode to switch to a read-only planning phase. In plan mode, you can only read files and write to the plan file.",
        "input_schema": {"type": "object", "properties": {}},
        "deferred": True,
    },
    {
        "name": "exit_plan_mode",
        "description": "Exit plan mode after you have finished writing your plan to the plan file.",
        "input_schema": {"type": "object", "properties": {}},
        "deferred": True,
    },
    {
        "name": "agent",
        "description": "Launch a sub-agent to handle a task autonomously. Sub-agents have isolated context and return their result. Types: 'explore' (read-only), 'plan' (read-only, structured planning), 'general' (full tools).",
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "Short (3-5 word) description of the sub-agent's task"},
                "prompt": {"type": "string", "description": "Detailed task instructions for the sub-agent"},
                "type": {"type": "string", "enum": ["explore", "plan", "general"], "description": "Agent type. Default: general"},
            },
            "required": ["description", "prompt"],
        },
    },
    # ─── Tool search (deferred tool loader) ─────────────────────
    {
        "name": "tool_search",
        "description": "Search for available tools by name or keyword. Returns full schema definitions for matching deferred tools so you can use them.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Tool name or search keywords"},
            },
            "required": ["query"],
        },
    },
]


async def _execute_tool(block):
    if block['name'] == 'list_files':
        return list_files(block['input'])
    if block["name"] == 'read_file':
        return read_files(block['input'])
    if block["name"] == "write_file":
        return write_files(block["input"])
    if block["name"] == "edit_file":
        return edit_files(block["input"])
    return f"unknow tool: {block['name']}"


# 加载本地文件
def load_settings(file_path) -> dict | None:
    if not file_path.exists():
        return None
    try:
        # 不传 encoding默认系统编码（window上可能是 GBK），建议显式写
       return json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        return None

# 检查下用户本地文件权限设置
def load_permission_rules() -> dict:
    # 地址拼接 Path.home 固定的用户主目录 Path.cwd 用户当前的工作目录
    user_settings_path = Path.home() / ".my-claude" / "user_settings.json"
    project_settings_path = Path.cwd() / ".my-claude" / "project_settings.json"
    # 读取 json 文件
    user_settings = load_settings(user_settings_path)
    project_settings = load_settings(project_settings_path)

    allow: list[dict] = []
    deny: list[dict] = []

    for settings in [user_settings, project_settings]:
        if not settings or "permissions" not in settings:
            continue
        perms = settings.get('permissions')
        if perms.get('allow'):
            allow.append(perms.get('allow'))
        if perms.get('deny'):
            deny.append(perms.get('deny'))

    return {"allow":allow, "deny":deny}

# 检查文件类型是否匹配
def _match_rules(rule, tool_name, inp) -> bool:
    if rule["tool"] != tool_name:
        return False
    if rule["pattern"] is None:
        return True
    return True

def check_permission(tool_name:str, inp:dict, permission_mode) -> dict:
    """Return {"action":"allow/deny/confirm"}"""
    if permission_mode == 'byPassPermissions':
        return {"action":"allow"}
    # 检查用户项目中是否设置权限在 setting.json中
    result_rules = load_permission_rules()
    for allow in result_rules['allow']:
        if _match_rules(allow, tool_name, inp):
            return {"action":"allow"}
    for deny in result_rules['deny']:
        if _match_rules(deny, tool_name, inp):
          return {"action":"deny"}
    if tool_name in CONCURRENCY_SAFE_TOOLS:
        return {"action":"allow"}
    return {"action":"allow"}

# edit_files {'file_path': '/Users/wangly/Documents/study/pythons/my-mini-claude/test.txt', 'old_string': 'include = ["mini_claude*"]', 'new_string': 'include = ["mini_claude*"]\n\n你好
# 王豆豆'}

# 比较
def _generate_diff(old_content, old_string, new_string) -> str:
    # 不改动的内容
    no_change = old_content.split(old_string)[0]
    start_line = len(no_change.split("\n"))
    old_lines = old_string.split("\n")
    new_lines = new_string.split("\n")
    # diff 格式  @@ -line_num,len(old_lines) +line_num,len(new_lines) @@
    #               └──────┬──────────────┘ └──────┬───────────────┘
    #                  旧文件的范围              新文件的范围
    part = [f"@@ -{start_line},{len(old_lines)} +{start_line},{len(new_lines)} @@"]
    for l in old_lines:
        part.append(f"-{l}")
    for l in new_lines:
        part.append(f"+{l}")
    return "\n".join(part)

def edit_files(inp) -> str:
    target_path = Path(inp["file_path"])
    content = target_path.read_text(encoding="utf-8")
    # old_string 在内容中出现的次数
    old_count= content.count(inp['old_string'])
    if old_count == 0:
        return f"Error: old_string not found in {inp['file_path']}"
    if old_count > 1:
        return f"Error: old_string found {old_count} times in {inp['file_path']}. Must be unique."
    new_content = content.replace(inp["old_string"], inp["new_string"])
    target_path.write_text(new_content, encoding="utf-8")
    # diff = _generate_diff(content, inp['old_string'], inp["new_string"])
    diff = "\n".join(difflib.unified_diff(content.splitlines(), new_content.splitlines(),lineterm=""))
    return f'Successfully edit {inp["file_path"]} \n {diff}'


# write_files inp ：{'file_path': '/Users/wangly/Documents/study/pythons/my-mini-claude/test.txt', 'content': ''}
def write_files(inp) -> str:
    write_path = Path(inp["file_path"])
    # 如果没有先创建 如果存在也不报错 .mkdir是实例方法 不建议直接 Path.mkdir使用
    write_path.parent.mkdir(parents=True, exist_ok=True)
    # write_text 不存在则创建 存在则覆盖
    write_path.write_text(inp["content"], encoding="utf-8")
    lines = inp["content"].split("\n")
    count = len(lines)
    preview = "\n".join(f"{i+1:4d}|{line}" for i, line in enumerate(lines))
    total = f"\n... {count} lines total" if count > 30 else ''
    return f"Successfully wrote to {inp['file_path']} \n {preview}\n{total}"

# list_file
def list_files(inp) -> str:
    base = Path(inp.get('path') or '.')
    # print(f"\n base: {base}")
    pattern = inp['pattern']
    files = []
    for f in base.glob(pattern):
        # print(f"\n f: {f}")
        if f.is_file():
            rel = str(f.relative_to(base) if base != Path('.') else f)
            # 不收集.git .idea
            if ".git" in rel.split(os.sep):
                continue
            print(f"rel: {rel},type: {type(rel)}")
            files.append(rel)
    if not files:
        return "当前目录没有可以查看的文件"
    return "\n".join(files)

# read_files
def read_files(inp) -> str:
   try:
       content = Path(inp['file_path']).read_text(encoding="utf-8")
       # print(f"read_files content: {content}")
       lines = content.split("\n")
       # enumerate() 返回下标与值（0,"a"）(1,"b")...
       # {i+1:4d} :d是十进制整数  4 = 占 4 个位置的空字符  右对齐补空格
       lines_with_numbers = (f"{i + 1:4d} | {line}" for i, line in enumerate(lines))
       return "\n".join(lines_with_numbers)
   except Exception as e:
       return f"Error read_file:{e}"