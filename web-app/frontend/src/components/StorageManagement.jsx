import { useCallback, useEffect, useMemo, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Tabs from "@mui/material/Tabs";
import Tab from "@mui/material/Tab";
import Icon from "./Icon";
import { cleanupStorage, getStorageReport } from "../lib/auth";
import { useGlobalMessage } from "./GlobalMessageProvider";

function formatBytes(value) {
  const bytes = Number(value) || 0;
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let amount = bytes;
  let unit = -1;
  while (amount >= 1024 && unit < units.length - 1) {
    amount /= 1024;
    unit += 1;
  }
  return `${amount.toFixed(amount >= 10 ? 0 : 1)} ${units[unit]}`;
}

function formatDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}

const sections = [
  { id: "orphan", label: "无记录任务目录", get: (report) => report?.task_dirs?.orphan || [] },
  { id: "part", label: ".part 临时文件", get: (report) => report?.part_files || [] },
  { id: "failed", label: "失败任务产物", get: (report) => report?.failed_tasks || [] },
  { id: "missing", label: "缺失任务目录", get: (report) => (report?.missing_dirs || []).map((path) => ({ path })) },
  { id: "bgm", label: "BGM 孤儿文件", get: (report) => report?.bgm_orphans || [] },
];

export default function StorageManagement() {
  const [report, setReport] = useState(null);
  const [activeSection, setActiveSection] = useState("orphan");
  const [loading, setLoading] = useState(true);
  const [cleaning, setCleaning] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const { showSuccess } = useGlobalMessage();

  const loadReport = useCallback(async () => {
    setLoading(true);
    try {
      setReport(await getStorageReport());
    } catch {
      // 全局请求层负责显示错误提示。
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadReport();
  }, [loadReport]);

  const handleCleanup = useCallback(async () => {
    setCleaning(true);
    try {
      const result = await cleanupStorage(false);
      showSuccess(`清理完成，释放 ${formatBytes(result.freed_bytes)}。`);
      setConfirmOpen(false);
      await loadReport();
    } catch {
      // 全局请求层负责显示错误提示。
    } finally {
      setCleaning(false);
    }
  }, [loadReport, showSuccess]);

  const disk = report?.disk;
  const activeRows = useMemo(
    () => sections.find((section) => section.id === activeSection)?.get(report) || [],
    [activeSection, report]
  );
  const cleanableCount = [
    ...(report?.task_dirs?.orphan || []),
    ...(report?.part_files || []),
    ...(report?.failed_tasks || []),
  ].filter((item) => item.deletable).length;
  const statusLabel = disk?.reject ? "低水位" : "正常";
  const statusDescription = disk?.reject ? "已暂停新任务" : "可继续创建任务";

  return (
    <section className="workspace-panel admin-panel" aria-label="存储管理工作区">
      <div className="admin-content">
        {loading && <div className="form-alert completed">正在扫描存储目录...</div>}
        {disk && (
          <div className="storage-summary">
            <div>
              <span className="field-label">剩余空间</span>
              <strong>{formatBytes(disk.free_bytes)}</strong>
              <small>{disk.free_percent}% / 共 {formatBytes(disk.total_bytes)}</small>
            </div>
            <div>
              <span className="field-label">保护阈值</span>
              <strong>{formatBytes(disk.min_free_bytes)}</strong>
              <small>或剩余 {disk.min_free_percent}%</small>
            </div>
            <div className="storage-summary-status">
              <span className="field-label">状态</span>
              <Chip
                icon={<Icon name={disk.reject ? "alert" : "check"} size={14} />}
                label={statusLabel}
                variant="outlined"
                title={disk.reject ? "已触发磁盘低水位保护" : "磁盘状态正常"}
                sx={{
                  alignSelf: "flex-start",
                  width: "fit-content",
                  minHeight: 28,
                  borderColor: disk.reject ? "var(--brand-300)" : "var(--success-300)",
                  backgroundColor: disk.reject ? "var(--brand-50)" : "var(--success-50)",
                  color: disk.reject ? "var(--brand-700)" : "var(--success-700)",
                  "& .MuiChip-icon": { color: "inherit" },
                }}
              />
              <small>{statusDescription}</small>
            </div>
            <Button
              variant="outlined"
              size="small"
              onClick={loadReport}
              disabled={loading}
              startIcon={<Icon name="refresh" size={16} />}
            >
              重新扫描
            </Button>
          </div>
        )}
        <div className="storage-actions">
          <div>
            <strong>预计可释放 {formatBytes(report?.reclaimable_bytes)}</strong>
            <span>
              包含过期孤儿目录、失败任务产物和 .part 临时文件，BGM 孤儿文件只报告不删除。
            </span>
          </div>
          <Button
            variant="contained"
            color="error"
            disabled={loading || cleaning || cleanableCount === 0}
            onClick={() => setConfirmOpen(true)}
            startIcon={<Icon name={cleaning ? "loading" : "trash"} size={16} />}
          >
            执行清理
          </Button>
        </div>
        <Tabs
          value={activeSection}
          onChange={(_, value) => setActiveSection(value)}
          variant="scrollable"
          sx={{ minHeight: 40, "& .MuiTab-root": { minHeight: 40, fontSize: 13 } }}
        >
          {sections.map((section) => (
            <Tab
              key={section.id}
              value={section.id}
              label={`${section.label} (${section.get(report).length})`}
            />
          ))}
        </Tabs>
        {activeSection === "missing" ? (
          <Alert severity="info">数据库中仍有任务记录，但对应目录不存在。此类项目不会被清理。</Alert>
        ) : activeSection === "bgm" ? (
          <Alert severity="info">BGM 与公共音色属于业务资源，当前只提供报告，不会自动删除。</Alert>
        ) : null}
        <TableContainer>
          <Table aria-label="存储扫描结果">
            <TableHead>
              <TableRow>
                <TableCell>路径</TableCell>
                <TableCell>大小</TableCell>
                <TableCell>修改时间</TableCell>
                <TableCell>状态</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {activeRows.map((item) => (
                <TableRow key={item.path}>
                  <TableCell sx={{ maxWidth: 520, wordBreak: "break-all" }}>
                    {item.path}
                  </TableCell>
                  <TableCell>{formatBytes(item.size_bytes)}</TableCell>
                  <TableCell>{formatDate(item.mtime)}</TableCell>
                  <TableCell>
                    {item.deletable ? (
                      <Chip size="small" label="可清理" color="warning" />
                    ) : (
                      <Chip size="small" label="保留" />
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
        {!loading && activeRows.length === 0 && <div className="audio-empty">暂无记录</div>}
      </div>
      <Dialog
        open={confirmOpen}
        onClose={() => !cleaning && setConfirmOpen(false)}
        maxWidth="xs"
        fullWidth
      >
        <DialogTitle>确认执行存储清理？</DialogTitle>
        <DialogContent>
          <p className="admin-reset-target">
            将删除 {cleanableCount} 项过期目录或临时文件，预计释放 {formatBytes(report?.reclaimable_bytes)}。
            失败任务数据库记录会保留，BGM 孤儿文件不会删除。
          </p>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmOpen(false)} disabled={cleaning}>
            取消
          </Button>
          <Button
            variant="contained"
            color="error"
            onClick={handleCleanup}
            disabled={cleaning}
            startIcon={<Icon name={cleaning ? "loading" : "trash"} size={16} />}
          >
            确认清理
          </Button>
        </DialogActions>
      </Dialog>
    </section>
  );
}
