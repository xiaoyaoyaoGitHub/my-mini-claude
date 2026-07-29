from pathlib import Path
import shlex
import re
from dataclasses import dataclass
from .formatter import parse_frontmatter

@dataclass
class SkillDefinition:
    name: str
    description: str
    when_to_use: str | None = None
    allowed_tools: list[str] | None = None
    user_invocable: bool = True
    context: str = "inline"
    prompt_template: str = ""
    source: str = "project"
    skill_dir: str = ""


_cache_skills: list[SkillDefinition] | None = None
# 查找 skill
def discover_skills() -> list[SkillDefinition]:
    global _cache_skills
    if _cache_skills is not None:
        return _cache_skills
    # 查找当前启动目录下的 skills
    skills_path = Path.cwd() / ".my_claude" / "skills"
    _skills = {}
    # 如果不是文件夹
    if not skills_path.is_dir():
        return _skills
    # 枚举文件夹下的 skills
    for skill_dir in skills_path.iterdir():
        # print(f"dir: {skill_dir}")
        if skill_dir.is_dir():
            skill_file = skill_dir / "SKILL.md"
            context = skill_file.read_text()
            raw = parse_frontmatter(context)
            meta = raw.meta
            skill_name = meta.get("name") or "unknow"
            _skills[skill_name] = SkillDefinition(
                name = skill_name,
                description = meta.get("description") or "",
                prompt_template= raw.body,
                skill_dir= skill_dir,
            )
    # print(f"found {len(_skills)} skills")
    _cache_skills = list(_skills.values())
    return _cache_skills

# 通过名称匹配 skill
def get_skill_by_name(name:str) -> SkillDefinition | None:
    for s in discover_skills():
        if s.name == name:
            return s
    return None

# 整合 skill  message
# {'args': '__main__.py', 'skill_name': 'summary'}
def execute_skill(inp) -> dict | None:
    skill_name = inp["skill_name"]
    skill = get_skill_by_name(skill_name)
    args = inp.get("args",'')
    if not skill:
        return None
    return {
        "prompt": resolve_skill_prompt(skill, args),
        "allowed_tools": skill.allowed_tools,
        "context": skill.context
    }

# 根据 skill 整合提示词模板
def resolve_skill_prompt(skill:SkillDefinition, args) -> str:
    prompt = skill.prompt_template
    # print(f"resolve prompt:{prompt}")
    # 解析参数
    try:
        args_list = shlex.split(args)
    except Exception as e:
        args_list = args.split()
    # 判断模板中是否有需要替换的位置 关键字 $ARGUMENTS
    has_placeholder = "$ARGUMENTS" in prompt or re.search(r"\$\d", prompt)

    # TODO 如果在模板中需要有参数进行替换 目前没有看到 等看到有合适的 skill再添加

    # 提示词模板中没有参数可以替换 直接追接到提示词后面
    if args and not has_placeholder:
        prompt += f"\n\nARGUMENTS:{args}"
    return prompt