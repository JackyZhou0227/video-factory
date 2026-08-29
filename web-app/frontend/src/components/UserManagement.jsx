import { useCallback, useEffect, useState } from "react";
import Button from "@mui/material/Button";
import Typography from "@mui/material/Typography";
import IconButton from "@mui/material/IconButton";
import Chip from "@mui/material/Chip";
import TextField from "@mui/material/TextField";
import MenuItem from "@mui/material/MenuItem";
import Tooltip from "@mui/material/Tooltip";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Dialog from "@mui/material/Dialog";
import DialogTitle from "@mui/material/DialogTitle";
import DialogContent from "@mui/material/DialogContent";
import DialogActions from "@mui/material/DialogActions";
import Icon from "./Icon";
import { listUsers, resetUserPassword, updateUserRole } from "../lib/auth";
import { useGlobalMessage } from "./GlobalMessageProvider";

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

function UserRow({ user, currentUserId, onOpenReset, onOpenRole, onRoleChange, resettingUserId, updatingRoleUserId }) {
  const isResetting = resettingUserId === user.id;
  const isUpdatingRole = updatingRoleUserId === user.id;
  const nextRole = user.is_admin ? "user" : "admin";
  const isCurrentUser = currentUserId === user.id;

  const handleRoleChange = useCallback(() => {
    onRoleChange(user.id, nextRole);
  }, [nextRole, onRoleChange, user.id]);

  return (
    <TableRow>
      <TableCell>
        <strong className="user-name">{user.display_name || user.username}</strong>
      </TableCell>
      <TableCell>
        <span className="user-username">{user.username}</span>
      </TableCell>
      <TableCell>
        <Chip
          icon={<Icon name={user.is_admin ? "shield" : "user"} size={14} />}
          label={user.is_admin ? "管理员" : "普通用户"}
          sx={{
            minHeight: 32,
            padding: "0 14px",
            borderRadius: "16px",
            fontSize: 12,
            fontWeight: 600,
            backgroundColor: user.is_admin ? "#f0f3ea" : "var(--surface-muted)",
            color: user.is_admin ? "#4f5d3a" : "var(--text-muted)",
            "& .MuiChip-icon": { color: "inherit" },
          }}
        />
      </TableCell>
      <TableCell>{formatDateTime(user.created_at)}</TableCell>
      <TableCell>
        <div className="user-row-actions">
          <Tooltip title="权限管理" arrow>
            <span>
              <IconButton
                type="button"
                aria-label={`权限管理：${user.display_name || user.username}`}
                onClick={() => onOpenRole(user)}
                disabled={isUpdatingRole || isCurrentUser}
                size="small"
              >
                <Icon name={isUpdatingRole ? "loading" : "shield"} size={16} />
              </IconButton>
            </span>
          </Tooltip>
          <Tooltip title="重置密码" arrow>
            <span>
              <IconButton
                type="button"
                aria-label={`重置密码：${user.display_name || user.username}`}
                onClick={() => onOpenReset(user)}
                disabled={isResetting}
                size="small"
              >
                <Icon name={isResetting ? "loading" : "key"} size={16} />
              </IconButton>
            </span>
          </Tooltip>
        </div>
      </TableCell>
    </TableRow>
  );
}

export default function UserManagement({ currentUser }) {
  const [filters, setFilters] = useState({ name: "", username: "" });
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [total, setTotal] = useState(0);
  const [resettingUserId, setResettingUserId] = useState("");
  const [updatingRoleUserId, setUpdatingRoleUserId] = useState("");
  const [resetUser, setResetUser] = useState(null);
  const [resetPassword, setResetPassword] = useState("");
  const [roleDialog, setRoleDialog] = useState(null);
  const [roleDraft, setRoleDraft] = useState("user");
  const { showSuccess } = useGlobalMessage();

  const openRoleDialog = useCallback((user) => {
    setRoleDialog(user);
    setRoleDraft(user.is_admin ? "admin" : "user");
  }, []);

  const updateFilter = useCallback((field, value) => {
    setFilters((current) => ({ ...current, [field]: value }));
    setPage(1);
  }, []);

  const loadUsers = useCallback(async (targetPage = 1) => {
    setLoading(true);
    try {
      const data = await listUsers({
        name: filters.name,
        username: filters.username,
        page: targetPage,
        pageSize: 20,
      });
      setUsers(Array.isArray(data.users?.items) ? data.users.items : []);
      setPage(data.users?.page || targetPage);
      setPages(Math.max(1, data.users?.pages || 1));
      setTotal(data.users?.total || 0);
    } catch {
      // 错误已由全局提示展示
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    // 文本筛选防抖后异步查询
    const timer = window.setTimeout(() => loadUsers(1), 400);
    return () => window.clearTimeout(timer);
  }, [loadUsers]);

  const generatePassword = useCallback(() => {
    const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%^&*";
    const values = new Uint32Array(14);
    crypto.getRandomValues(values);
    setResetPassword(Array.from(values, (value) => alphabet[value % alphabet.length]).join(""));
  }, []);

  const openResetDialog = useCallback((user) => {
    setResetUser(user);
    setResetPassword("");
  }, []);

  const closeResetDialog = useCallback(() => {
    if (resettingUserId) return;
    setResetUser(null);
    setResetPassword("");
  }, [resettingUserId]);

  const handlePasswordReset = useCallback(async () => {
      setResettingUserId(resetUser.id);

      try {
        const data = await resetUserPassword(resetUser.id, resetPassword);
        setUsers((current) => current.map((user) => (user.id === data.user.id ? data.user : user)));
        showSuccess("密码已重置，该用户的现有登录已作废，需要使用新密码重新登录。");
        setResetUser(null);
        setResetPassword("");
      } catch {
        // 错误已由全局提示展示
      } finally {
        setResettingUserId("");
      }
    }, [resetPassword, resetUser, showSuccess]);

  const handleRoleChange = useCallback(async (userId, role) => {
    setUpdatingRoleUserId(userId);

    try {
      const data = await updateUserRole(userId, role);
      setUsers((current) => current.map((user) => (user.id === data.user.id ? data.user : user)));
      showSuccess(role === "admin" ? "用户已设为管理员。" : "用户已设为普通用户。");
    } catch {
      // 错误已由全局提示展示
    } finally {
      setUpdatingRoleUserId("");
    }
  }, [showSuccess]);

  return (
    <section className="workspace-panel admin-panel" aria-label="用户管理工作区">
      <div className="admin-content">
        <div className="task-filter-grid admin-filter-grid">
          <TextField
            className="field"
            label="名称"
            placeholder="按显示名称模糊搜索"
            fullWidth
            size="small"
            value={filters.name}
            onChange={(event) => updateFilter("name", event.target.value)}
          />
          <TextField
            className="field"
            label="用户名"
            placeholder="按用户名模糊搜索"
            fullWidth
            size="small"
            value={filters.username}
            onChange={(event) => updateFilter("username", event.target.value)}
          />
        </div>

        {loading && <div className="form-alert completed">正在读取用户列表...</div>}

        <div className="task-list-toolbar"><span>共 {total} 个用户</span></div>

        <TableContainer>
          <Table aria-label="用户列表">
            <TableHead>
              <TableRow>
                <TableCell>名称</TableCell>
                <TableCell>用户名</TableCell>
                <TableCell>角色</TableCell>
                <TableCell>创建时间</TableCell>
                <TableCell>操作</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {users.map((user) => (
                <UserRow
                  key={user.id}
                  user={user}
                  currentUserId={currentUser?.id}
                  onOpenReset={openResetDialog}
                  onOpenRole={openRoleDialog}
                  onRoleChange={handleRoleChange}
                  resettingUserId={resettingUserId}
                  updatingRoleUserId={updatingRoleUserId}
                />
              ))}
            </TableBody>
          </Table>
        </TableContainer>

        {!loading && users.length === 0 && <div className="audio-empty">暂无用户</div>}

        <div className="task-pagination">
          <Button type="button" variant="outlined" size="small" disabled={page <= 1 || loading} onClick={() => loadUsers(page - 1)}>
            上一页
          </Button>
          <span>第 {page} / {pages} 页</span>
          <Button type="button" variant="outlined" size="small" disabled={page >= pages || loading} onClick={() => loadUsers(page + 1)}>
            下一页
          </Button>
        </div>
      </div>
      <Dialog
        open={Boolean(roleDialog)}
        onClose={() => setRoleDialog(null)}
        aria-labelledby="user-role-title"
        fullWidth
        maxWidth="xs"
      >
        <DialogTitle id="user-role-title">权限管理</DialogTitle>
        <DialogContent>
          <p className="admin-reset-target">
            正在调整 <strong>{roleDialog?.display_name || roleDialog?.username}</strong> 的账号角色
          </p>
          <TextField
            className="field"
            label="账号角色"
            fullWidth
            size="small"
            select
            value={roleDraft}
            onChange={(event) => setRoleDraft(event.target.value)}
          >
            <MenuItem value="admin">管理员</MenuItem>
            <MenuItem value="user">普通用户</MenuItem>
          </TextField>
          <p className="field-help">系统会保留至少一个管理员账号。</p>
        </DialogContent>
        <DialogActions>
          <Button type="button" onClick={() => setRoleDialog(null)}>取消</Button>
          <Button
            type="button"
            variant="contained"
            disabled={Boolean(updatingRoleUserId) || roleDraft === (roleDialog?.is_admin ? "admin" : "user")}
            onClick={() => {
              const target = roleDialog;
              setRoleDialog(null);
              if (target && roleDraft !== (target.is_admin ? "admin" : "user")) {
                handleRoleChange(target.id, roleDraft);
              }
            }}
          >
            确认
          </Button>
        </DialogActions>
      </Dialog>
      <Dialog
        open={Boolean(resetUser)}
        onClose={() => { if (!resettingUserId) closeResetDialog(); }}
        aria-labelledby="admin-reset-title"
        fullWidth
        maxWidth="xs"
      >
        <DialogTitle sx={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", pr: 1.5 }}>
          <div>
            <Typography variant="kicker" component="span" className="section-kicker">Account security</Typography>
            <h3 id="admin-reset-title">重置用户密码</h3>
          </div>
          <IconButton onClick={closeResetDialog} disabled={Boolean(resettingUserId)} aria-label="关闭" title="关闭" size="small">
            <Icon name="x" size={17} />
          </IconButton>
        </DialogTitle>
        <DialogContent>
          <p className="admin-reset-target">正在为 <strong>{resetUser?.display_name || resetUser?.username}</strong> 设置新密码</p>
          <div className="admin-reset-field">
            <TextField
              id="admin-reset-password"
              className="field"
              label="新密码"
              fullWidth
              size="small"
              type="text"
              value={resetPassword}
              onChange={(event) => setResetPassword(event.target.value)}
              slotProps={{ htmlInput: { minLength: 8 } }}
              autoComplete="new-password"
              autoFocus
            />
            <Button type="button" variant="outlined" size="small" onClick={generatePassword} startIcon={<Icon name="refresh" size={16} />}>随机密码</Button>
          </div>
          <p className="field-help">密码至少 8 位。重置后，该用户的现有登录会话将立即失效。</p>
        </DialogContent>
        <DialogActions>
          <Button type="button" onClick={closeResetDialog} disabled={Boolean(resettingUserId)}>取消</Button>
          <Button type="button" variant="contained" onClick={handlePasswordReset} disabled={resetPassword.length < 8 || Boolean(resettingUserId)}
            startIcon={<Icon name={resettingUserId ? "loading" : "key"} size={16} />}>
            {resettingUserId ? "正在重置" : "确认重置"}
          </Button>
        </DialogActions>
      </Dialog>
    </section>
  );
}
