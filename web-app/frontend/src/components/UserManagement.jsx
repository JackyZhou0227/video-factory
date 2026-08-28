import { useCallback, useEffect, useState } from "react";
import Icon from "./Icon";
import Alert from "./Alert";
import { listUsers, resetUserPassword, updateUserRole } from "../lib/auth";

function formatDateTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function UserRow({ user, currentUserId, onOpenReset, onRoleChange, resettingUserId, updatingRoleUserId }) {
  const isResetting = resettingUserId === user.id;
  const isUpdatingRole = updatingRoleUserId === user.id;
  const nextRole = user.is_admin ? "user" : "admin";
  const isCurrentUser = currentUserId === user.id;

  const handleRoleChange = useCallback(() => {
    onRoleChange(user.id, nextRole);
  }, [nextRole, onRoleChange, user.id]);

  return (
    <tr>
      <td>
        <div className="user-cell">
          <strong>{user.display_name || user.username}</strong>
          <span>{user.username}</span>
        </div>
      </td>
      <td>
        <div className="role-cell">
          <span className={`role-badge ${user.is_admin ? "admin" : "user"}`}>
            <Icon name={user.is_admin ? "shield" : "user"} size={14} />
            {user.is_admin ? "管理员" : "普通用户"}
          </span>
          <button
            className="text-button role-action"
            type="button"
            onClick={handleRoleChange}
            disabled={isUpdatingRole || isCurrentUser}
          >
            {isCurrentUser ? "当前账号" : isUpdatingRole ? "正在更新" : user.is_admin ? "设为普通用户" : "设为管理员"}
          </button>
        </div>
      </td>
      <td>{formatDateTime(user.created_at)}</td>
      <td>
        <button className="secondary-action inline-action" type="button" onClick={() => onOpenReset(user)} disabled={isResetting}>
            <Icon name={isResetting ? "loading" : "key"} size={15} />
            重置密码
          </button>
      </td>
    </tr>
  );
}

export default function UserManagement({ currentUser }) {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [resettingUserId, setResettingUserId] = useState("");
  const [updatingRoleUserId, setUpdatingRoleUserId] = useState("");
  const [resetUser, setResetUser] = useState(null);
  const [resetPassword, setResetPassword] = useState("");

  const generatePassword = useCallback(() => {
    const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%^&*";
    const values = new Uint32Array(14);
    crypto.getRandomValues(values);
    setResetPassword(Array.from(values, (value) => alphabet[value % alphabet.length]).join(""));
    setError("");
  }, []);

  const openResetDialog = useCallback((user) => {
    setResetUser(user);
    setResetPassword("");
    setError("");
  }, []);

  const closeResetDialog = useCallback(() => {
    if (resettingUserId) return;
    setResetUser(null);
    setResetPassword("");
  }, [resettingUserId]);

  const loadUsers = useCallback(async () => {
    setLoading(true);
    setError("");
    setNotice("");

    try {
      const data = await listUsers();
      setUsers(Array.isArray(data.users) ? data.users : []);
    } catch (err) {
      setError(err.message || "读取用户列表失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadUsers();
  }, [loadUsers]);

  const handlePasswordReset = useCallback(async () => {
      setError("");
      setNotice("");
      setResettingUserId(resetUser.id);

      try {
        const data = await resetUserPassword(resetUser.id, resetPassword);
        setUsers((current) => current.map((user) => (user.id === data.user.id ? data.user : user)));
        setNotice("密码已重置，该用户的现有登录已作废，需要使用新密码重新登录。");
        setResetUser(null);
        setResetPassword("");
      } catch (err) {
        setError(err.message || "重置密码失败");
      } finally {
        setResettingUserId("");
      }
    }, [resetPassword, resetUser]);

  const handleRoleChange = useCallback(async (userId, role) => {
    setError("");
    setNotice("");
    setUpdatingRoleUserId(userId);

    try {
      const data = await updateUserRole(userId, role);
      setUsers((current) => current.map((user) => (user.id === data.user.id ? data.user : user)));
      setNotice(role === "admin" ? "用户已设为管理员。" : "用户已设为普通用户。");
    } catch (err) {
      setError(err.message || "更新用户角色失败");
    } finally {
      setUpdatingRoleUserId("");
    }
  }, []);

  return (
    <section className="workspace-panel admin-panel" aria-label="用户管理工作区">
      <div className="admin-content">
        <div className="settings-copy admin-copy">
          <h3>
            <Icon name="user" size={18} />
            账号
          </h3>
          <p>
            忘记密码时，由管理员在这里给用户设置一个新密码。系统不会读取或展示原密码，重置后会让该用户现有登录失效。
            管理员也可以把其他用户设为管理员；系统会保留至少一个管理员账号。
          </p>
        </div>

        {loading && <div className="form-alert completed">正在读取用户列表...</div>}
        {notice && <Alert>{notice}</Alert>}
        {error && <Alert type="error">{error}</Alert>}

        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>用户</th>
                <th>角色</th>
                <th>创建时间</th>
                <th>重置密码</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <UserRow
                  key={user.id}
                  user={user}
                  currentUserId={currentUser?.id}
                  onOpenReset={openResetDialog}
                  onRoleChange={handleRoleChange}
                  resettingUserId={resettingUserId}
                  updatingRoleUserId={updatingRoleUserId}
                />
              ))}
            </tbody>
          </table>
        </div>

        {!loading && users.length === 0 && <div className="audio-empty">暂无用户</div>}

        <div className="settings-actions admin-actions">
          <button className="secondary-action" type="button" onClick={loadUsers} disabled={loading}>
            <Icon name={loading ? "loading" : "refresh"} size={16} />
            重新读取
          </button>
        </div>
      </div>
      {resetUser ? (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeResetDialog(); }}>
          <section className="modal-panel admin-reset-modal" role="dialog" aria-modal="true" aria-labelledby="admin-reset-title">
            <div className="modal-heading">
              <div>
                <span className="section-kicker">Account security</span>
                <h3 id="admin-reset-title">重置用户密码</h3>
              </div>
              <button className="icon-button" type="button" onClick={closeResetDialog} disabled={Boolean(resettingUserId)} aria-label="关闭" title="关闭">
                <Icon name="x" size={17} />
              </button>
            </div>
            <div className="modal-body">
              <p className="admin-reset-target">正在为 <strong>{resetUser.display_name || resetUser.username}</strong> 设置新密码</p>
              <div className="admin-reset-field">
                <label className="field" htmlFor="admin-reset-password"><span className="field-label">新密码</span><input id="admin-reset-password" className="control" type="text" value={resetPassword} onChange={(event) => setResetPassword(event.target.value)} minLength="8" autoComplete="new-password" autoFocus /></label>
                <button className="secondary-action" type="button" onClick={generatePassword}><Icon name="refresh" size={16} />随机密码</button>
              </div>
              <p className="field-help">密码至少 8 位。重置后，该用户的现有登录会话将立即失效。</p>
            </div>
            <div className="modal-actions">
              <button className="secondary-action" type="button" onClick={closeResetDialog} disabled={Boolean(resettingUserId)}>取消</button>
              <button className="primary-action" type="button" onClick={handlePasswordReset} disabled={resetPassword.length < 8 || Boolean(resettingUserId)}><Icon name={resettingUserId ? "loading" : "key"} size={16} />{resettingUserId ? "正在重置" : "确认重置"}</button>
            </div>
          </section>
        </div>
      ) : null}
    </section>
  );
}
