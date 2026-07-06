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

def print_user_prompt() -> None:
    console.print("[bold green]>[/bold green]",end="")


