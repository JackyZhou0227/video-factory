import { useCallback, useEffect, useMemo, useState } from "react";
import Icon from "./Icon";
import { listUsers, resetUserPassword, updateUserRole } from "../lib/auth";
import { PAGE_NAMES } from "../lib/pageNames";

function formatDateTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function UserRow({ user, currentUserId, onPasswordReset, onRoleChange, resettingUserId, updatingRoleUserId }) {
  const [password, setPassword] = useState("");
  const isResetting = resettingUserId === user.id;
  const isUpdatingRole = updatingRoleUserId === user.id;
  const canSubmit = password.length >= 8 && !isResetting;
  const nextRole = user.is_admin ? "user" : "admin";
  const isCurrentUser = currentUserId === user.id;

  const handleSubmit = useCallback(
    async (event) => {
      event.preventDefault();
      await onPasswordReset(user.id, password);
      setPassword("");
    },
    [onPasswordReset, password, user.id]
  );

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
        <form className="reset-password-form" onSubmit={handleSubmit}>
          <input
            className="control compact-control"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="至少 8 位新密码"
            autoComplete="new-password"
          />
          <button className="secondary-action inline-action" type="submit" disabled={!canSubmit}>
            <Icon name={isResetting ? "loading" : "key"} size={15} />
            重置
          </button>
        </form>
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

  const adminCount = useMemo(() => users.filter((user) => user.is_admin).length, [users]);

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

  const handlePasswordReset = useCallback(
    async (userId, password) => {
      setError("");
      setNotice("");
      setResettingUserId(userId);

      try {
        const data = await resetUserPassword(userId, password);
        setUsers((current) => current.map((user) => (user.id === data.user.id ? data.user : user)));
        setNotice("密码已重置，该用户需要使用新密码重新登录。");
      } catch (err) {
        setError(err.message || "重置密码失败");
      } finally {
        setResettingUserId("");
      }
    },
    []
  );

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
    <section className="workspace-panel admin-panel" aria-labelledby="admin-title">
      <div className="panel-heading settings-heading">
        <div>
          <span className="section-kicker">{PAGE_NAMES.userManagement}</span>
          <h2 id="admin-title">用户管理</h2>
        </div>
        <span className="status-pill completed">
          <Icon name="shield" size={14} />
          {adminCount} 个管理员
        </span>
      </div>

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
        {notice && <div className="form-alert completed">{notice}</div>}
        {error && <div className="form-alert failed">{error}</div>}

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
                  onPasswordReset={handlePasswordReset}
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
    </section>
  );
}
