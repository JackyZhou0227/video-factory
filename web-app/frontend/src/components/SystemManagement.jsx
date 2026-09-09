import { useEffect, useState } from "react";
import Tabs from "@mui/material/Tabs";
import Tab from "@mui/material/Tab";
import UserManagement from "./UserManagement";
import OrganizationManagement from "./OrganizationManagement";
import StorageManagement from "./StorageManagement";

export default function SystemManagement({ currentUser }) {
  const [activeTab, setActiveTab] = useState("users");
  const isSuperAdmin = Boolean(currentUser?.is_admin);

  // 权限降级或账号切换时，避免保留只对超管开放的页签。
  useEffect(() => {
    if (!isSuperAdmin && activeTab !== "users") setActiveTab("users");
  }, [activeTab, isSuperAdmin]);

  return (
    <section className="settings-main system-management-shell" aria-label="系统管理工作区">
      <Tabs
        value={activeTab}
        onChange={(_, value) => setActiveTab(value)}
        sx={{
          px: 3,
          pt: 2,
          minHeight: 44,
          "& .MuiTab-root": { minHeight: 44, fontSize: 14, fontWeight: 650 },
        }}
      >
        <Tab value="users" label="用户管理" />
        {isSuperAdmin && <Tab value="organizations" label="组织管理" />}
        {isSuperAdmin && <Tab value="storage" label="存储管理" />}
      </Tabs>
      {activeTab === "organizations" && isSuperAdmin ? (
        <OrganizationManagement embedded />
      ) : activeTab === "storage" && isSuperAdmin ? (
        <StorageManagement />
      ) : (
        <UserManagement currentUser={currentUser} />
      )}
    </section>
  );
}
