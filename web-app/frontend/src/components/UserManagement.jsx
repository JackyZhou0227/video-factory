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
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import Icon from "./Icon";
import OrganizationManagement from "./OrganizationManagement";
import {
  createMember,
  listOrganizations,
  listUsers,
  rejectPendingUser,
  resetUserPassword,
  updateUserOrg,
  updateUserRole,
  updateUserStatus,
} from "../lib/auth";
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

function UserRow({ user, currentUserId, canManageRoles, onOpenReset, onOpenRole, onRoleChange, onApprove, onReject, resettingUserId, updatingRoleUserId, actingUserId }) {
  const isResetting = resettingUserId === user.id;
  const isUpdatingRole = updatingRoleUserId === user.id;
  const isActing = actingUserId === user.id;
  const nextRole = user.is_admin ? "user" : user.is_org_admin ? "user" : "org_admin";
  const isCurrentUser = currentUserId === user.id;
  const isPending = user.status === "pending";

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
        {isPending ? (
          <Chip
            label="待审批"
            sx={{
              minHeight: 32,
              padding: "0 14px",
              borderRadius: "16px",
              fontSize: 12,
              fontWeight: 600,
              backgroundColor: "#fdf3e3",
              color: "#9a6b1f",
            }}
          />
        ) : (
          <Chip
            icon={<Icon name={user.is_admin ? "shield" : user.is_org_admin ? "list" : "user"} size={14} />}
            label={user.is_admin ? "超级管理员" : user.is_org_admin ? "组织管理员" : "普通用户"}
            sx={{
              minHeight: 32,
              padding: "0 14px",
              borderRadius: "16px",
              fontSize: 12,
              fontWeight: 600,
              backgroundColor: user.is_admin ? "#f0f3ea" : user.is_org_admin ? "#e8f0f5" : "var(--surface-muted)",
              color: user.is_admin ? "#4f5d3a" : user.is_org_admin ? "#33566b" : "var(--text-muted)",
              "& .MuiChip-icon": { color: "inherit" },
            }}
          />
        )}
      </TableCell>
      <TableCell>{user.org_name || "-"}</TableCell>
      <TableCell>{formatDateTime(user.created_at)}</TableCell>
      <TableCell>
        <div className="user-row-actions">
          {isPending ? (
            <>
              <Tooltip title="批准加入" arrow>
                <span>
                  <IconButton
                    type="button"
                    aria-label={`批准：${user.display_name || user.username}`}
                    onClick={() => onApprove(user)}
                    disabled={isActing}
                    size="small"
                  >
                    <Icon name={isActing ? "loading" : "check"} size={16} />
                  </IconButton>
                </span>
              </Tooltip>
              <Tooltip title="驳回申请" arrow>
                <span>
                  <IconButton
                    type="button"
                    aria-label={`驳回：${user.display_name || user.username}`}
                    onClick={() => onReject(user)}
                    disabled={isActing}
                    size="small"
                  >
                    <Icon name="x" size={16} />
                  </IconButton>
                </span>
              </Tooltip>
            </>
          ) : (
            <>
              {canManageRoles && (
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
              )}
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
            </>
          )}
        </div>
      </TableCell>
    </TableRow>
  );
}

export default function UserManagement({ currentUser }) {
  const canManageRoles = Boolean(currentUser?.is_admin);
  const [activeTab, setActiveTab] = useState("members");
  const [filters, setFilters] = useState({ name: "", username: "", status: "" });
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [total, setTotal] = useState(0);
  const [resettingUserId, setResettingUserId] = useState("");
  const [updatingRoleUserId, setUpdatingRoleUserId] = useState("");
  const [actingUserId, setActingUserId] = useState("");
  const [resetUser, setResetUser] = useState(null);
  const [resetPassword, setResetPassword] = useState("");
  const [roleDialog, setRoleDialog] = useState(null);
  const [roleDraft, setRoleDraft] = useState("user");
  const [orgs, setOrgs] = useState([]);
  const [orgDraft, setOrgDraft] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createForm, setCreateForm] = useState({ username: "", displayName: "", password: "" });
  const { showSuccess } = useGlobalMessage();

  const openRoleDialog = useCallback((user) => {
    setRoleDialog(user);
    setRoleDraft(user.is_admin ? "admin" : user.is_org_admin ? "org_admin" : "user");
    setOrgDraft(user.org_id || "");
    if (currentUser?.is_admin) {
      listOrganizations()
        .then((data) => setOrgs(Array.isArray(data.organizations) ? data.organizations : []))
        .catch(() => setOrgs([]));
    }
  }, [currentUser]);

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
        status: filters.status,
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

  const handleRoleChange = useCallback(async (userId, role, orgId) => {
    setUpdatingRoleUserId(userId);

    try {
      let data = null;
      if (orgId !== undefined) {
        data = await updateUserOrg(userId, orgId || null);
      }
      if (role) {
        data = await updateUserRole(userId, role);
      }
      if (data?.user) {
        setUsers((current) => current.map((user) => (user.id === data.user.id ? data.user : user)));
      }
      showSuccess("账号设置已更新。");
    } catch {
      // 错误已由全局提示展示
    } finally {
      setUpdatingRoleUserId("");
    }
  }, [showSuccess]);

  const handleApprove = useCallback(async (user) => {
    setActingUserId(user.id);
    try {
      await updateUserStatus(user.id, "active");
      showSuccess(`已批准 ${user.display_name || user.username} 加入。`);
      await loadUsers(page);
    } catch {
      // 错误已由全局提示展示
    } finally {
      setActingUserId("");
    }
  }, [loadUsers, page, showSuccess]);

  const handleReject = useCallback(async (user) => {
    setActingUserId(user.id);
    try {
      await rejectPendingUser(user.id);
      showSuccess("已驳回该注册申请。");
      await loadUsers(page);
    } catch {
      // 错误已由全局提示展示
    } finally {
      setActingUserId("");
    }
  }, [loadUsers, page, showSuccess]);

  const handleCreateMember = useCallback(async () => {
    setCreating(true);
    try {
      await createMember({
        username: createForm.username.trim(),
        password: createForm.password,
        displayName: createForm.displayName,
      });
      showSuccess("成员已创建并激活。");
      setCreateOpen(false);
      setCreateForm({ username: "", displayName: "", password: "" });
      await loadUsers(1);
    } catch {
      // 错误已由全局提示展示
    } finally {
      setCreating(false);
    }
  }, [createForm, loadUsers, showSuccess]);

  return (
    <section className="workspace-panel admin-panel" aria-label="用户管理工作区">
      <div className="admin-content">
        {currentUser?.is_admin && (
          <Tabs
            value={activeTab}
            onChange={(_, value) => setActiveTab(value)}
            sx={{ mb: 2, minHeight: 40, "& .MuiTab-root": { minHeight: 40, fontSize: 14, fontWeight: 600 } }}
          >
            <Tab value="members" label="成员管理" />
            <Tab value="organizations" label="组织管理" />
          </Tabs>
        )}
        {activeTab === "organizations" && currentUser?.is_admin ? (
          <OrganizationManagement embedded />
        ) : (
          <>
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
          <div className="field">
            <span className="field-label">账号状态</span>
            <TextField
              fullWidth
              size="small"
              select
              value={filters.status}
              onChange={(event) => updateFilter("status", event.target.value)}
            >
              <MenuItem value="">全部</MenuItem>
              <MenuItem value="active">正常</MenuItem>
              <MenuItem value="pending">待审批</MenuItem>
            </TextField>
          </div>
          <div className="field" style={{ display: "flex", alignItems: "center" }}>
            <Button
              type="button"
              variant="contained"
              size="small"
              onClick={() => setCreateOpen(true)}
              startIcon={<Icon name="user" size={16} />}
            >
              创建成员
            </Button>
          </div>
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
                <TableCell>组织</TableCell>
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
                  canManageRoles={canManageRoles}
                  onOpenReset={openResetDialog}
                  onOpenRole={openRoleDialog}
                  onRoleChange={handleRoleChange}
                  onApprove={handleApprove}
                  onReject={handleReject}
                  resettingUserId={resettingUserId}
                  updatingRoleUserId={updatingRoleUserId}
                  actingUserId={actingUserId}
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
          </>
        )}
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
          <div className="field">
            <span className="field-label">账号角色</span>
            <TextField
              fullWidth
              size="small"
              select
              value={roleDraft}
              onChange={(event) => setRoleDraft(event.target.value)}
            >
              <MenuItem value="admin">超级管理员</MenuItem>
              <MenuItem value="org_admin">组织管理员</MenuItem>
              <MenuItem value="user">普通用户</MenuItem>
            </TextField>
          </div>
          {currentUser?.is_admin && (
            <div className="field" style={{ marginTop: 12 }}>
              <span className="field-label">所属组织</span>
              <TextField
                fullWidth
                size="small"
                select
                value={orgDraft}
                onChange={(event) => setOrgDraft(event.target.value)}
              >
                <MenuItem value="">未分配</MenuItem>
                {orgs.map((org) => (
                  <MenuItem key={org.id} value={org.id}>{org.name}</MenuItem>
                ))}
              </TextField>
            </div>
          )}
          <p className="field-help">组织管理员需要先归属组织；系统会保留至少一个超级管理员。</p>
        </DialogContent>
        <DialogActions>
          <Button type="button" onClick={() => setRoleDialog(null)}>取消</Button>
          <Button
            type="button"
            variant="contained"
            disabled={Boolean(updatingRoleUserId) || (roleDraft === (roleDialog?.is_admin ? "admin" : roleDialog?.is_org_admin ? "org_admin" : "user") && orgDraft === (roleDialog?.org_id || ""))}
            onClick={() => {
              const target = roleDialog;
              setRoleDialog(null);
              if (!target) return;
              const currentRole = target?.is_admin ? "admin" : target?.is_org_admin ? "org_admin" : "user";
              const roleChanged = roleDraft !== currentRole;
              const orgChanged = orgDraft !== (target.org_id || "");
              if (roleChanged || orgChanged) {
                handleRoleChange(target.id, roleChanged ? roleDraft : undefined, orgChanged ? orgDraft : undefined);
              }
            }}
          >
            确认
          </Button>
        </DialogActions>
      </Dialog>
      <Dialog
        open={createOpen}
        onClose={() => { if (!creating) setCreateOpen(false); }}
        aria-labelledby="admin-create-title"
        fullWidth
        maxWidth="xs"
      >
        <DialogTitle id="admin-create-title">创建成员</DialogTitle>
        <DialogContent>
          <div style={{ display: "grid", gap: 12, paddingTop: 4 }}>
            <TextField
              id="admin-create-username"
              className="field"
              label="用户名"
              fullWidth
              size="small"
              value={createForm.username}
              onChange={(event) => setCreateForm((c) => ({ ...c, username: event.target.value }))}
              placeholder="3-32 位英文、数字或下划线"
              slotProps={{ htmlInput: { minLength: 3 } }}
              required
            />
            <TextField
              id="admin-create-display-name"
              className="field"
              label="显示名称"
              fullWidth
              size="small"
              value={createForm.displayName}
              onChange={(event) => setCreateForm((c) => ({ ...c, displayName: event.target.value }))}
              placeholder="可选"
            />
            <TextField
              id="admin-create-password"
              className="field"
              label="初始密码"
              fullWidth
              size="small"
              type="text"
              value={createForm.password}
              onChange={(event) => setCreateForm((c) => ({ ...c, password: event.target.value }))}
              helperText="至少 8 位，创建后成员可直接登录。"
              slotProps={{ htmlInput: { minLength: 8 } }}
              required
            />
          </div>
        </DialogContent>
        <DialogActions>
          <Button type="button" onClick={() => setCreateOpen(false)} disabled={Boolean(creating)}>取消</Button>
          <Button
            type="button"
            variant="contained"
            onClick={handleCreateMember}
            disabled={creating || createForm.username.trim().length < 3 || createForm.password.length < 8}
            startIcon={<Icon name={creating ? "loading" : "user"} size={16} />}
          >
            {creating ? "正在创建" : "确认创建"}
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
