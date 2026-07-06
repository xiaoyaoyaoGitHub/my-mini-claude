import anthropic

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
        self.mode = model
        self.base_url = base_url
        self.api_key = api_key
        self.thinking = thinking
        # 创建 anthropic 异步客户端
        self._anthropic_client = anthropic.AsyncAnthropic(api_key=self.api_key, base_url=self.base_url)
