import json
import re
import shutil
import zipfile
from pathlib import Path


FRONTEND_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = FRONTEND_ROOT / "skills"
PUBLIC_SKILLS_ROOT = FRONTEND_ROOT / "public" / "skills"
SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
REQUIRED_FILES = ("SKILL.md", "skill.json")


def load_metadata(skill_dir: Path) -> dict:
    metadata_path = skill_dir / "skill.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    if metadata.get("id") != skill_dir.name:
        raise ValueError(f"{metadata_path}: id 必须与目录名一致")
    if not SEMVER_PATTERN.fullmatch(str(metadata.get("version", ""))):
        raise ValueError(f"{metadata_path}: version 必须使用 SemVer，例如 1.0.0")
    for field in ("display_name", "released_at", "summary"):
        if not str(metadata.get(field, "")).strip():
            raise ValueError(f"{metadata_path}: 缺少字段 {field}")
    for relative_path in REQUIRED_FILES:
        if not (skill_dir / relative_path).is_file():
            raise FileNotFoundError(f"{skill_dir}: 缺少 {relative_path}")

    skill_content = (skill_dir / "SKILL.md").read_text(encoding="utf-8-sig")
    if "agent_created: true" not in skill_content:
        raise ValueError(f"{skill_dir / 'SKILL.md'}: 缺少 agent_created: true 元数据")
    if (skill_dir / "agents" / "openai.yaml").exists():
        raise ValueError(f"{skill_dir}: 不应包含 agents/openai.yaml")

    return metadata


def package_skill(skill_dir: Path) -> Path:
    metadata = load_metadata(skill_dir)
    output_dir = PUBLIC_SKILLS_ROOT / metadata["id"]
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / f'{metadata["id"]}-{metadata["version"]}.zip'

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source_path in sorted(skill_dir.rglob("*")):
            if not source_path.is_file() or "__pycache__" in source_path.parts:
                continue
            relative_path = source_path.relative_to(skill_dir)
            archive_path_in_zip = Path(skill_dir.name) / relative_path
            archive.write(source_path, archive_path_in_zip.as_posix())

    return archive_path


def main() -> None:
    skill_dirs = sorted(
        path
        for path in SKILLS_ROOT.iterdir()
        if path.is_dir() and (path / "skill.json").is_file()
    )
    if not skill_dirs:
        raise FileNotFoundError(f"{SKILLS_ROOT}: 没有找到可打包的 Skill")

    if PUBLIC_SKILLS_ROOT.exists():
        shutil.rmtree(PUBLIC_SKILLS_ROOT)
    PUBLIC_SKILLS_ROOT.mkdir(parents=True, exist_ok=True)

    for skill_dir in skill_dirs:
        archive_path = package_skill(skill_dir)
        print(f"Packaged {skill_dir.name} -> {archive_path.relative_to(FRONTEND_ROOT)}")


if __name__ == "__main__":
    main()
