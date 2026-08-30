import { useCallback, useState } from "react";
import Button from "@mui/material/Button";
import Typography from "@mui/material/Typography";
import IconButton from "@mui/material/IconButton";
import TextField from "@mui/material/TextField";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogTitle from "@mui/material/DialogTitle";
import DialogContent from "@mui/material/DialogContent";
import Icon from "./Icon";
import Alert from "./Alert";
import { changePassword, updateProfile } from "../lib/auth";
import { useGlobalMessage } from "./GlobalMessageProvider";

export default function UserProfile({ currentUser, onUserUpdated, onLoggedOut }) {
  const [passwordView, setPasswordView] = useState(false);
  const [displayName, setDisplayName] = useState(currentUser?.display_name || currentUser?.username || "");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [savingProfile, setSavingProfile] = useState(false);
  const [changingPassword, setChangingPassword] = useState(false);
  const [error, setError] = useState("");
  const { showSuccess } = useGlobalMessage();

  const saveProfile = useCallback(async (event) => {
    event.preventDefault();
    setSavingProfile(true);
    try {
      const data = await updateProfile(displayName.trim());
      onUserUpdated?.(data.user);
      showSuccess("个人资料已保存。");
    } catch {
      // 错误已由全局提示展示
    } finally {
      setSavingProfile(false);
    }
  }, [displayName, onUserUpdated, showSuccess]);

  const submitPasswordChange = useCallback(async (event) => {
    event.preventDefault();
    if (newPassword !== confirmPassword) {
      setError("两次输入的新密码不一致。");
      return;
    }
    setChangingPassword(true);
    try {
      await changePassword(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      showSuccess("密码已修改，请重新登录。");
      window.setTimeout(() => onLoggedOut?.(), 500);
    } catch {
      // 错误已由全局提示展示
    } finally {
      setChangingPassword(false);
    }
  }, [confirmPassword, currentPassword, newPassword, onLoggedOut, showSuccess]);

  const switchView = useCallback((nextView) => {
    setPasswordView(nextView);
    setError("");
  }, []);

  return (
    <section className="workspace-panel profile-panel" aria-label="个人资料工作区">
      <div className="profile-content">
        <form className="profile-form" onSubmit={saveProfile}>
          <TextField
            className="field"
            label="用户名"
            fullWidth
            size="small"
            value={currentUser?.username || ""}
            slotProps={{ input: { readOnly: true } }}
            sx={{ "& .MuiOutlinedInput-root": { backgroundColor: "var(--surface-muted)" } }}
          />
          <TextField className="field" label="显示名称" fullWidth size="small" slotProps={{ htmlInput: { maxLength: 64 } }} value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
          <div className="profile-role">
            <span className="field-label">账号角色</span>
            <Chip
              icon={<Icon name={currentUser?.is_admin ? "shield" : currentUser?.is_org_admin ? "list" : "user"} size={14} />}
              label={currentUser?.is_admin ? "超级管理员" : currentUser?.is_org_admin ? "组织管理员" : "普通用户"}
              sx={{
                justifyContent: "center",
                justifySelf: "start",
                minHeight: 32,
                padding: "0 14px",
                borderRadius: "16px",
                fontSize: 12,
                fontWeight: 600,
                backgroundColor: currentUser?.is_admin ? "#f0f3ea" : currentUser?.is_org_admin ? "#e8f0f5" : "var(--surface-muted)",
                color: currentUser?.is_admin ? "#4f5d3a" : currentUser?.is_org_admin ? "#33566b" : "var(--text-muted)",
                "& .MuiChip-icon": { color: "inherit" },
              }}
            />
          </div>
          <Button type="submit" variant="contained" disabled={savingProfile} startIcon={<Icon name={savingProfile ? "loading" : "save"} size={16} />}>{savingProfile ? "正在保存" : "保存资料"}</Button>
        </form>
        <div className="profile-security-row">
          <div><strong>账号密码</strong><p>定期更新密码，保护账号安全。</p></div>
          <Button type="button" variant="outlined" size="small" onClick={() => switchView(true)} startIcon={<Icon name="lock" size={16} />}>修改密码</Button>
        </div>
      </div>
      <Dialog
        open={passwordView}
        onClose={() => { if (!changingPassword) switchView(false); }}
        aria-labelledby="profile-password-title"
        fullWidth
        maxWidth="xs"
      >
        <DialogTitle sx={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", pr: 1.5 }}>
          <div>
            <Typography variant="kicker" component="span" className="section-kicker">Account security</Typography>
            <h3 id="profile-password-title">修改密码</h3>
            <p>修改后所有已登录设备都会退出，需要使用新密码重新登录。</p>
          </div>
          <IconButton onClick={() => switchView(false)} disabled={changingPassword} aria-label="关闭" title="关闭" size="small">
            <Icon name="x" size={17} />
          </IconButton>
        </DialogTitle>
        <DialogContent>
          <form className="profile-form" onSubmit={submitPasswordChange}>
            <TextField className="field" label="当前密码" fullWidth size="small" type="password" autoComplete="current-password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} autoFocus />
            <TextField className="field" label="新密码" fullWidth size="small" type="password" autoComplete="new-password" slotProps={{ htmlInput: { minLength: 8 } }} value={newPassword} onChange={(event) => setNewPassword(event.target.value)} />
            <TextField className="field" label="确认新密码" fullWidth size="small" type="password" autoComplete="new-password" slotProps={{ htmlInput: { minLength: 8 } }} value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} />
            <div className="modal-actions">
              <Button type="button" variant="outlined" onClick={() => switchView(false)} disabled={changingPassword}>取消</Button>
              <Button type="submit" variant="contained" disabled={changingPassword} startIcon={<Icon name={changingPassword ? "loading" : "save"} size={16} />}>{changingPassword ? "正在修改" : "修改密码"}</Button>
            </div>
          </form>
          {error ? <Alert type="error">{error}</Alert> : null}
        </DialogContent>
      </Dialog>
    </section>
  );
}
