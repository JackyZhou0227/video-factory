import IconButton from "@mui/material/IconButton";
import Tooltip from "@mui/material/Tooltip";
import Icon from "./Icon";

export default function SkillHeaderCard({ skill, icon = "wand" }) {
  const filename = `${skill.id}-${skill.version}.zip`;
  const downloadUrl = `${import.meta.env.BASE_URL}skills/${skill.id}/${filename}`;
  const titleId = `${skill.id}-skill-title`;

  return (
    <section className="skill-header-card" aria-labelledby={titleId}>
      <span className="skill-header-icon" aria-hidden="true"><Icon name={icon} size={21} /></span>
      <div className="skill-header-content">
        <div className="skill-header-heading">
          <strong id={titleId}>{skill.display_name}</strong>
          <span className="skill-header-version">最新版 v{skill.version}</span>
        </div>
        <p>配套 Skill：{skill.summary}。</p>
        <small>请与您当前使用的下载文件名或 <code>skill.json</code> 手动对比版本。</small>
      </div>
      <Tooltip title="下载" arrow>
        <IconButton
          className="skill-header-download"
          href={downloadUrl}
          download={filename}
          aria-label={`下载${skill.display_name}`}
          size="small"
        >
          <Icon name="download" size={16} />
        </IconButton>
      </Tooltip>
    </section>
  );
}
