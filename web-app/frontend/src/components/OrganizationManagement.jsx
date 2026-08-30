import { useCallback, useEffect, useState } from "react";
import Button from "@mui/material/Button";
import IconButton from "@mui/material/IconButton";
import TextField from "@mui/material/TextField";
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
import { createOrganization, deleteOrganization, listOrganizations, renameOrganization } from "../lib/auth";
import { useGlobalMessage } from "./GlobalMessageProvider";

export default function OrganizationManagement() {
  const [orgs, setOrgs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [editing, setEditing] = useState(null);
  const [editingName, setEditingName] = useState("");
  const [actingId, setActingId] = useState("");
  const { showSuccess } = useGlobalMessage();

  const loadOrgs = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listOrganizations();
      setOrgs(Array.isArray(data.organizations) ? data.organizations : []);
    } catch {
      // 错误已由全局提示展示
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadOrgs();
  }, [loadOrgs]);

  const handleCreate = useCallback(async () => {
    setSubmitting(true);
    try {
      await createOrganization(name.trim());
      showSuccess("组织已创建。");
      setName("");
      await loadOrgs();
    } catch {
      // 错误已由全局提示展示
    } finally {
      setSubmitting(false);
    }
  }, [loadOrgs, name, showSuccess]);

  const handleRename = useCallback(async () => {
    setActingId(editing.id);
    try {
      await renameOrganization(editing.id, editingName.trim());
      showSuccess("组织已改名。");
      setEditing(null);
      await loadOrgs();
    } catch {
      // 错误已由全局提示展示
    } finally {
      setActingId("");
    }
  }, [editing, editingName, loadOrgs, showSuccess]);

  const handleDelete = useCallback(async (org) => {
    setActingId(org.id);
    try {
      await deleteOrganization(org.id);
      showSuccess("组织已删除。");
      await loadOrgs();
    } catch {
      // 错误已由全局提示展示
    } finally {
      setActingId("");
    }
  }, [loadOrgs, showSuccess]);

  return (
    <section className="workspace-panel admin-panel" aria-label="组织管理工作区">
      <div className="admin-content">
        <div className="task-filter-grid admin-filter-grid">
          <TextField
            className="field"
            label="组织名称"
            placeholder="输入名称后点击创建"
            fullWidth
            size="small"
            value={name}
            onChange={(event) => setName(event.target.value)}
            slotProps={{ htmlInput: { maxLength: 64 } }}
          />
          <div className="field" style={{ display: "flex", alignItems: "center" }}>
            <Button
              type="button"
              variant="contained"
              size="small"
              onClick={handleCreate}
              disabled={submitting || !name.trim()}
              startIcon={<Icon name={submitting ? "loading" : "list"} size={16} />}
            >
              {submitting ? "创建中..." : "创建组织"}
            </Button>
          </div>
        </div>

        {loading && <div className="form-alert completed">正在读取组织列表...</div>}

        <div className="task-list-toolbar"><span>共 {orgs.length} 个组织</span></div>

        <TableContainer>
          <Table aria-label="组织列表">
            <TableHead>
              <TableRow>
                <TableCell>组织名称</TableCell>
                <TableCell>成员数</TableCell>
                <TableCell>创建时间</TableCell>
                <TableCell>操作</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {orgs.map((org) => (
                <TableRow key={org.id}>
                  <TableCell><strong className="user-name">{org.name}</strong></TableCell>
                  <TableCell>{org.member_count}</TableCell>
                  <TableCell>{org.created_at?.slice(0, 10)}</TableCell>
                  <TableCell>
                    <div className="user-row-actions">
                      <Tooltip title="改名" arrow>
                        <span>
                          <IconButton
                            type="button"
                            aria-label={`改名：${org.name}`}
                            size="small"
                            onClick={() => { setEditing(org); setEditingName(org.name); }}
                          >
                            <Icon name="type" size={16} />
                          </IconButton>
                        </span>
                      </Tooltip>
                      <Tooltip title={org.member_count > 0 ? "需先移出全部成员" : "删除组织"} arrow>
                        <span>
                          <IconButton
                            type="button"
                            aria-label={`删除：${org.name}`}
                            size="small"
                            disabled={org.member_count > 0 || actingId === org.id}
                            onClick={() => handleDelete(org)}
                          >
                            <Icon name={actingId === org.id ? "loading" : "x"} size={16} />
                          </IconButton>
                        </span>
                      </Tooltip>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>

        {!loading && orgs.length === 0 && <div className="audio-empty">暂无组织，请先创建。</div>}

        <Dialog
          open={Boolean(editing)}
          onClose={() => { if (actingId !== editing?.id) setEditing(null); }}
          aria-labelledby="org-rename-title"
          fullWidth
          maxWidth="xs"
        >
          <DialogTitle id="org-rename-title">组织改名</DialogTitle>
          <DialogContent>
            <TextField
              className="field"
              label="新名称"
              fullWidth
              size="small"
              value={editingName}
              onChange={(event) => setEditingName(event.target.value)}
              slotProps={{ htmlInput: { maxLength: 64 } }}
              sx={{ mt: 1 }}
            />
          </DialogContent>
          <DialogActions>
            <Button type="button" onClick={() => setEditing(null)} disabled={actingId === editing?.id}>取消</Button>
            <Button
              type="button"
              variant="contained"
              onClick={handleRename}
              disabled={actingId === editing?.id || !editingName.trim() || editingName.trim() === editing?.name}
            >
              确认
            </Button>
          </DialogActions>
        </Dialog>
      </div>
    </section>
  );
}
