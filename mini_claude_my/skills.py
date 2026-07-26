from pathlib import Path
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
    # TODO 枚举文件夹下的 skills
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
                when_to_use = meta.get("description") or "",
                prompt_template= raw.body,
                skill_dir= skill_dir,
            )
    # print(f"found {len(_skills)} skills")
    _cache_skills = list(_skills.values())
    return _cache_skills
