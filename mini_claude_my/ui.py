
import time
import sys
# threading 是 Python 标准库，提供基于线程的并发——在一个进程里跑多个执行流（线程），它们共享内存、能同时干活。适合 I/O
#   密集型任务（网络请求、文件读写、等外部资源），不适合 CPU 密集型（被 GIL 卡住，应改用 multiprocessing）。
import threading
from rich.console import Console
console = Console()

# 打印错误日志
def print_error(message:str) -> None:
    console.print(f" [bold red]Error:{message}[/bold red] ")

# 打印欢迎语
def print_welcome() -> None:
    console.print(f"\n [bold cyan]Welcome my-mini-claude [/bold cyan][dim] A minimal coding agent[/dim]\n")
    console.print("[dim]Type your request, or 'exit' to quit.[/dim]")
    console.print('[dim]Commands: /clear /plan /cost /compact /memory /skills[/dim]')

# 打印用户输入
def print_user_prompt() -> None:
    console.print("[bold green]>[/bold green]",end="")

# 打印 thinking
def print_assistant_prompt(thinking) -> None:
    console.print(f"[dim]{thinking}[/dim]", end="")
    # sys.stdout.write(thinking)
    # sys.stdout.flush()

# 开始thinking

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
# threading.Thread 一个独立的执行流 跑目标函数
_spinner_thread: threading.Thread | None = None
_spinner_stop = threading.Event()

def start_spinner() -> None:
    global _spinner_thread
    # 如果存在则返回
    if _spinner_thread is not None:
        return
    # 把标志位重置为 False
    _spinner_stop.clear()
    # 否则创建
    def _run():
        frame = 0
        sys.stdout.write(f"{SPINNER_FRAMES[frame]} thinking...")
        sys.stdout.flush()
        # 粘性（sticky）：set() 之后标志位一直是 True，直到有人主动 clear()。所有后续 wait() 立刻返回，不会"错过"信号。
        # is_set() 检查当前标志位
        while not _spinner_stop.is_set():
            time.sleep(0.08)
            frame = (frame + 1) % len(SPINNER_FRAMES)
            sys.stdout.write(f"\r {SPINNER_FRAMES[frame]} thinking...")
            sys.stdout.flush()

    # daemon=True 设为守护线程（主进程退出时自动死）
    _spinner_thread = threading.Thread(target=_run, daemon=True)
    _spinner_thread.start()

def stop_spinner() -> None:
    global _spinner_thread
    # 如果不存在则返回
    if _spinner_thread is None:
        return
    # 将标志位设值为 True
    _spinner_stop.set()
    #
    _spinner_thread.join(timeout=1)
    _spinner_thread = None
    sys.stdout.write("\r\033[K")
    sys.stdout.flush()
