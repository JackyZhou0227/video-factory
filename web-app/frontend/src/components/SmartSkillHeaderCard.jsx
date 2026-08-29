import IconButton from "@mui/material/IconButton";
import Tooltip from "@mui/material/Tooltip";
import Icon from "./Icon";
import smartEditingSkill from "../../skills/generate-smart-edit-copy/skill.json";

const SMART_EDITING_SKILL_FILENAME = `${smartEditingSkill.id}-${smartEditingSkill.version}.zip`;
const SMART_EDITING_SKILL_DOWNLOAD_URL = `${import.meta.env.BASE_URL}skills/${smartEditingSkill.id}/${SMART_EDITING_SKILL_FILENAME}`;

export default function SmartSkillHeaderCard() {
  return (
    <section className="smart-skill-card" aria-labelledby="smart-skill-title">
      <span className="smart-skill-icon" aria-hidden="true"><Icon name="wand" size={21} /></span>
      <div className="smart-skill-content">
        <div className="smart-skill-heading">
          <strong id="smart-skill-title">智能剪辑文案与关键词</strong>
          <span className="smart-skill-version">最新版 v{smartEditingSkill.version}</span>
        </div>
        <p>配套 Skill：{smartEditingSkill.summary}。</p>
        <small>请与您当前使用的下载文件名或 <code>skill.json</code> 手动对比版本。</small>
      </div>
      <Tooltip title="下载" arrow>
        <IconButton
          className="smart-skill-download"
          href={SMART_EDITING_SKILL_DOWNLOAD_URL}
          download={SMART_EDITING_SKILL_FILENAME}
          aria-label="下载"
          size="small"
        >
          <Icon name="download" size={16} />
        </IconButton>
      </Tooltip>
    </section>
  );
}
