
# Python 标准库 argparse 用来存放解析后的命令行参数的对象
# argparse.Namespace 就是简单的容器对象 可以用属性访问
import argparse
import os
import sys
import asyncio
import signal
from dotenv import load_dotenv
load_dotenv() # 用于读取.env中的配置变量

from .ui import print_error,print_welcome,print_user_prompt
from .agent import Agent

# 命令行参数解析
def parse_args() -> argparse.Namespace:
    print(f"使用 argparse 解析入参 返回")
    parser = argparse.ArgumentParser(
        prog="mini_claude_my", # 程序名 用于 usage行和错误信息里
        description="自定义的 mini claude code", # 帮助文本里 usage 行下方、参数列表上方的简短说明
        add_help=False, # 是否自定义添加-h / --help 选项
    )
    # 参数解析
    """
    parser.add_argument(
        name_or_flags...,     # 必填，位置或关键字
        action='store',       # 收到参数时怎么处理
        nargs=None,           # 收几个值
        const=None,           # action=store_const / nargs='?' 用的常量
        default=None,         # 没传时的默认值
        type=None,            # 类型转换函数
        choices=None,         # 允许的取值列表
        required=False,       # 可选参数是否必填
        help=None,            # 帮助文本
        metavar=None,         # usage 里显示的占位名
        dest=None,            # Namespace 上的属性名
    )
    """
    parser.add_argument('prompt', nargs="*", help="one-shot prompt")
    parser.add_argument('--yolo', '-y', action="store_true", help="skip all confirmation prompts")
    parser.add_argument("--plan", action="store_true", help="Plan mode：read-only")
    parser.add_argument('--accept-edits',action="store_true", help="auto-approve file edits")
    parser.add_argument("--dont-ask", action="store_true", help="auto-deny confirmation (for CI)")
    parser.add_argument("--thinking", action="store_true", help="enable extended thinking")
    parser.add_argument('--model', '-m', default=None, help="Model to use")
    parser.add_argument('--base_url',default=None, help="API base path")
    parser.add_argument('--resume', action="store_true", help="Resume last session")
    parser.add_argument('--max-cost', type=float, default=None, help="Max USD spend")
    parser.add_argument('--max-turns', type=int, default=None, help="max agentic turns")
    parser.add_argument('--help', '-h', action="store_true", help="show help")
    # 该方法返回的就是Namespace 实例
    return parser.parse_args()

# 解析运行模式
def _resolve_permission_mode(args: argparse.Namespace) -> str:
    if args.yolo:
        return "byPassPermissions"
    if args.plan:
        return "plan"
    if args.accept_edits:
        return "acceptEdits"
    if args.dont_ask:
        return "dontAsk"
    return 'default'

async def run_repl(agent:Agent) -> None:
    """Interactive REPL loop."""
    # 信号中断次数 ctrl + C 按下次数
    sigint_count = 0

    def handler_abort(signum, frame):
        # print(f"\n收到信号{signum}")
        nonlocal sigint_count
        sigint_count += 1
        if sigint_count >= 2:
            print(f"\nBye")
            sys.exit(0)
    # ctrl + C  会触发 handler_abort
    signal.signal(signal.SIGINT, handler_abort)
    print_welcome()
    while True:
        print_user_prompt()

        try:
            line = input()
        except (EOFError, KeyboardInterrupt):
            print('\nBye!\n')
            break
        # 去掉用户输入的首尾所有空白类字符
        inp = line.strip()
        if not inp:
            continue
        if inp in ('exit','quit'):
            print('\nBye!Bye!\n')
            break
        # TODO 开始给 agent 发送信息
        try:
             await agent.chat(inp)
        except Exception as error:
            print(f'\nBye!Bye! {error}\n')


def main() -> None:
    print("hello mini-claude")
    # 解析交互式对话框的参数 使用到argparse
    args = parse_args()
    print(args)
    if args.help:
        print("""
            Usage: mini-claude [options] [prompt]

Options:
  --yolo, -y          Skip all confirmation prompts (bypassPermissions mode)
  --plan              Plan mode: read-only, describe changes without executing
  --accept-edits      Auto-approve file edits, still confirm dangerous shell
  --dont-ask          Auto-deny anything needing confirmation (for CI)
  --thinking          Enable extended thinking (Anthropic only)
  --model, -m         Model to use (default: claude-opus-4-6, or MINI_CLAUDE_MODEL env)
  --api-base URL      Use OpenAI-compatible API endpoint (key via env var)
  --resume            Resume the last session
  --max-cost USD      Stop when estimated cost exceeds this amount
  --max-turns N       Stop after N agentic turns
  --help, -h          Show this help

REPL commands:
  /clear              Clear conversation history
  /plan               Toggle plan mode (read-only <-> normal)
  /cost               Show token usage and cost
  /compact            Manually compact conversation
  /memory             List saved memories
  /skills             List available skills
  /<skill-name>       Invoke a skill (e.g. /commit "fix types")

Examples:
  my-mini-claude "fix the bug in src/app.ts"
  my-mini-claude --yolo "run all tests and fix failures"
  my-mini-claude --plan "how would you refactor this?"
  my-mini-claude --max-cost 0.50 --max-turns 20 "implement feature X"
  OPENAI_API_KEY=sk-xxx mini-claude --api-base https://aihubmix.com/v1 --model gpt-4o "hello"
  my-mini-claude --resume
  my-mini-claude  # starts interactive REPL
        """)
        # 退出程序 不往下执行
        sys.exit(0)
    # 模式确认
    permission_mode = _resolve_permission_mode(args)
    print(f"permission mode:{permission_mode}")
    # 访问模型 如果不设置用环境变量配置中的模型
    model = args.model or os.environ.get('MINI_CLAUDE_MODEL', 'claude-opus-4-6')
    print(f"model:{model}")
    # 自定义请求地址 默认读取本地 .env环境参数 使用 anthropic
    base_url = args.base_url or os.environ.get('ANTHROPIC_BASE_URL',None)
    print(f"base_url:{base_url},thinking:{args.thinking}")
    api_key = os.environ.get('ANTHROPIC_API_KEY',None)
    if not base_url or not api_key:
        print_error( "API key and BASE URL is required .\n"
            "  Set ANTHROPIC_API_KEY (+ optional ANTHROPIC_BASE_URL) for Anthropic format,\n")
        # 1 表示 一般错误
        sys.exit(1)
    # 创建 agent
    agent = Agent(
        api_key=api_key,
        base_url=base_url,
        permission_mode=permission_mode,
        model=model,
        thinking=args.thinking,
    )
    # 开启 REPL
    # asyncio.run(coro, *, debug=False) 是 Python 3.7+ 提供的"程序入口"
    # 创建事件循环、跑一个协程到结束、清理、关循环，全自动一条龙
    asyncio.run(run_repl(agent))
if __name__ == "__main__":
    main()