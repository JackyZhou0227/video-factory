import { useEffect, useState } from "react";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import FormControlLabel from "@mui/material/FormControlLabel";
import IconButton from "@mui/material/IconButton";
import MenuItem from "@mui/material/MenuItem";
import Slider from "@mui/material/Slider";
import Switch from "@mui/material/Switch";
import TextField from "@mui/material/TextField";
import Icon from "./Icon";

export const DEFAULT_SUBTITLE_STYLE = {
  font_family: "Microsoft YaHei",
  font_size: 65,
  color: "#FFD21F",
  outline_color: "#000000",
  outline_width: 5,
  bottom_margin: 250,
  alignment: "center",
  notice_enabled: true,
  notice_text: "人文记录 无不良引导\n如有不适 请线上就医",
  notice_font_size: 33,
  notice_color: "#FFFFFF",
  notice_outline_color: "#000000",
  notice_outline_width: 1,
  notice_top_margin: 106,
};

export function cloneDefaultSubtitleStyle() {
  return { ...DEFAULT_SUBTITLE_STYLE };
}

function withOpacity(color, opacity) {
  const normalized = String(color || "").trim();
  return /^#[0-9a-f]{6}$/i.test(normalized) ? `${normalized}${opacity}` : normalized;
}

function subtitlePreviewStyle(style, type) {
  const isNotice = type === "notice";
  const fontSize = Number(isNotice ? style.notice_font_size : style.font_size) || 1;
  const outlineWidth = Number(isNotice ? style.notice_outline_width : style.outline_width) || 0;
  const color = isNotice ? style.notice_color : style.color;
  const outlineColor = isNotice ? withOpacity(style.notice_outline_color, "B0") : style.outline_color;
  const fontFamily = style.font_family || DEFAULT_SUBTITLE_STYLE.font_family;
  return {
    color,
    fontFamily: `"${fontFamily}", "Microsoft YaHei", sans-serif`,
    fontSize: `${(fontSize / 1920) * 100}cqh`,
    WebkitTextStroke: outlineWidth > 0 ? `${(outlineWidth / 1920) * 100}cqh ${outlineColor}` : undefined,
    textShadow: outlineWidth > 0 ? `0 0 ${(outlineWidth / 1920) * 1.5}cqh ${outlineColor}` : "none",
  };
}

function SubtitleStylePreview({ style }) {
  const noticeText = String(style.notice_text || "").trim();
  return (
    <div className="subtitle-style-preview" aria-label="字幕样式预览">
      <div className="subtitle-preview-canvas">
        <div className="subtitle-preview-backdrop" aria-hidden="true" />
        {style.notice_enabled && noticeText ? (
          <div className="subtitle-preview-notice" style={{ ...subtitlePreviewStyle(style, "notice"), top: `${(Number(style.notice_top_margin) / 1920) * 100}%` }}>
            {noticeText}
          </div>
        ) : null}
        <div className={`subtitle-preview-main is-${style.alignment || "center"}`} style={{ ...subtitlePreviewStyle(style, "subtitle"), bottom: `${(Number(style.bottom_margin) / 1920) * 100}%` }}>
          这是一段用于查看字幕样式的预览内容
        </div>
      </div>
    </div>
  );
}

export default function SubtitleSettings({
  idPrefix = "subtitle",
  enabled,
  onEnabledChange,
  style,
  onStyleChange,
  disabled = false,
}) {
  const [dialogOpen, setDialogOpen] = useState(false);
  useEffect(() => {
    if (!enabled) setDialogOpen(false);
  }, [enabled]);

  const updateStyle = (field, value) => onStyleChange({ ...style, [field]: value });
  const titleId = `${idPrefix}-subtitle-style-title`;

  return (
    <>
      <div className="subtitle-style-launcher">
        <div className="subtitle-style-launcher-copy">
          <span className="subtitle-style-launcher-icon"><Icon name="sliders" size={17} /></span>
          <div>
            <strong>字幕设置</strong>
            <small>{enabled ? (style.notice_enabled ? "显示主字幕与小字免责申明" : "显示主字幕，已隐藏小字免责申明") : "本次成片不显示字幕"}</small>
          </div>
        </div>
        <FormControlLabel
          className={`subtitle-enabled-control ${enabled ? "is-enabled" : ""}`}
          control={<Switch className="subtitle-enabled-switch" size="small" checked={enabled} onChange={(event) => onEnabledChange(event.target.checked)} disabled={disabled} />}
          label={enabled ? "显示字幕" : "关闭字幕"}
        />
        <Button className="subtitle-style-open" type="button" variant="outlined" size="small" onClick={() => setDialogOpen(true)} disabled={disabled || !enabled} startIcon={<Icon name="edit" size={15} />}>
          编辑样式
        </Button>
      </div>
      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} aria-labelledby={titleId} maxWidth="lg" fullWidth>
        <div className="subtitle-style-editor">
          <div className="subtitle-style-heading">
            <div><strong id={titleId}>字幕样式</strong><small>预览使用固定示例内容；成片仍按最终文案、分句和替换规则填充字幕</small></div>
            <div className="subtitle-style-heading-actions">
              <Button className="subtitle-style-reset" type="button" variant="outlined" size="small" onClick={() => onStyleChange(cloneDefaultSubtitleStyle())} startIcon={<Icon name="refresh" size={14} />}>恢复默认</Button>
              <IconButton type="button" onClick={() => setDialogOpen(false)} aria-label="关闭字幕样式编辑" size="small"><Icon name="x" size={17} /></IconButton>
            </div>
          </div>
          <div className="subtitle-style-layout">
            <SubtitleStylePreview style={style} />
            <div className="subtitle-style-controls">
              <section className="subtitle-style-section" aria-labelledby={`${idPrefix}-subtitle-main-title`}>
                <div className="subtitle-style-section-heading"><strong id={`${idPrefix}-subtitle-main-title`}>主字幕</strong><span>仅调整样式</span></div>
                <div className="subtitle-style-field-grid">
                  <TextField className="field" label="字体" fullWidth size="small" select value={style.font_family} onChange={(event) => updateStyle("font_family", event.target.value)}>
                    <MenuItem value="Microsoft YaHei">微软雅黑</MenuItem><MenuItem value="SimHei">黑体</MenuItem><MenuItem value="SimSun">宋体</MenuItem><MenuItem value="KaiTi">楷体</MenuItem>
                  </TextField>
                  <TextField className="field" label="对齐" fullWidth size="small" select value={style.alignment} onChange={(event) => updateStyle("alignment", event.target.value)}>
                    <MenuItem value="left">左对齐</MenuItem><MenuItem value="center">居中</MenuItem><MenuItem value="right">右对齐</MenuItem>
                  </TextField>
                </div>
                <div className="subtitle-style-slider-grid">
                  <div className="field"><span className="field-label">字号 {style.font_size}</span><Slider size="small" min={36} max={108} value={style.font_size} onChange={(_, value) => updateStyle("font_size", value)} /></div>
                  <div className="field"><span className="field-label">描边 {style.outline_width}</span><Slider size="small" min={0} max={12} value={style.outline_width} onChange={(_, value) => updateStyle("outline_width", value)} /></div>
                  <div className="field"><span className="field-label">底部边距 {style.bottom_margin}</span><Slider size="small" min={80} max={480} step={5} value={style.bottom_margin} onChange={(_, value) => updateStyle("bottom_margin", value)} /></div>
                </div>
                <div className="subtitle-style-swatch-grid"><label><span>文字</span><input type="color" value={style.color} onChange={(event) => updateStyle("color", event.target.value)} /></label><label><span>描边</span><input type="color" value={style.outline_color} onChange={(event) => updateStyle("outline_color", event.target.value)} /></label></div>
              </section>
              <section className="subtitle-style-section" aria-labelledby={`${idPrefix}-subtitle-notice-title`}>
                <div className="subtitle-style-section-heading"><strong id={`${idPrefix}-subtitle-notice-title`}>小字免责申明</strong><FormControlLabel control={<Switch size="small" checked={style.notice_enabled} onChange={(event) => updateStyle("notice_enabled", event.target.checked)} />} label={style.notice_enabled ? "显示" : "不显示"} /></div>
                {style.notice_enabled ? (
                  <>
                    <TextField className="field subtitle-notice-text-field" label="申明内容" fullWidth size="small" multiline rows={3} slotProps={{ htmlInput: { maxLength: 120 } }} value={style.notice_text} onChange={(event) => updateStyle("notice_text", event.target.value)} />
                    <div className="subtitle-style-slider-grid">
                      <div className="field"><span className="field-label">字号 {style.notice_font_size}</span><Slider size="small" min={18} max={58} value={style.notice_font_size} onChange={(_, value) => updateStyle("notice_font_size", value)} /></div>
                      <div className="field"><span className="field-label">描边 {style.notice_outline_width}</span><Slider size="small" min={0} max={6} value={style.notice_outline_width} onChange={(_, value) => updateStyle("notice_outline_width", value)} /></div>
                      <div className="field"><span className="field-label">顶部边距 {style.notice_top_margin}</span><Slider size="small" min={30} max={260} value={style.notice_top_margin} onChange={(_, value) => updateStyle("notice_top_margin", value)} /></div>
                    </div>
                    <div className="subtitle-style-swatch-grid"><label><span>文字</span><input type="color" value={style.notice_color} onChange={(event) => updateStyle("notice_color", event.target.value)} /></label><label><span>描边</span><input type="color" value={style.notice_outline_color} onChange={(event) => updateStyle("notice_outline_color", event.target.value)} /></label></div>
                  </>
                ) : <div className="subtitle-notice-hidden">小字免责申明不会显示在本次生成的成片中。</div>}
              </section>
            </div>
          </div>
          <div className="subtitle-style-modal-footer"><Button className="subtitle-style-confirm" type="button" variant="contained" onClick={() => setDialogOpen(false)} startIcon={<Icon name="check" size={15} />}>确认</Button></div>
        </div>
      </Dialog>
    </>
  );
}
