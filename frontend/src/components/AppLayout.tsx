import { AppShell, Button, Group, NavLink, Title } from "@mantine/core";
import { Link, Outlet, useLocation } from "react-router";

import { useRefreshAll } from "../hooks/useRefreshAll";
import { BackendStatus } from "./BackendStatus";

const NAV_ITEMS = [
  { label: "Projects", to: "/projects" },
  { label: "Activity", to: "/activity" },
  { label: "Settings", to: "/settings" },
];

export function AppLayout() {
  const location = useLocation();
  const { refresh, isRefreshing } = useRefreshAll();

  return (
    <AppShell header={{ height: 60 }} navbar={{ width: 220, breakpoint: "sm" }} padding="md">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Title order={3}>Visio Studio</Title>
          <Group gap="md">
            <BackendStatus />
            <Button variant="default" size="xs" onClick={refresh} loading={isRefreshing}>
              Refresh
            </Button>
          </Group>
        </Group>
      </AppShell.Header>
      <AppShell.Navbar p="md">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            component={Link}
            to={item.to}
            label={item.label}
            active={location.pathname.startsWith(item.to)}
          />
        ))}
      </AppShell.Navbar>
      <AppShell.Main>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}
