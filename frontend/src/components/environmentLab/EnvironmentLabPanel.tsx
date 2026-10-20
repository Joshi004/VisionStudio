import { useState } from "react";

import { EnvironmentDrawer } from "./EnvironmentDrawer";
import { EnvironmentLibrary } from "./EnvironmentLibrary";
import { EnvironmentPage } from "./EnvironmentPage";
import { useOpenEnvironment } from "./useOpenEnvironment";

type DrawerConfig = {
  opened: boolean;
  /** The environment to edit, or null for a new one. */
  environmentId: number | null;
};

/**
 * The Environments tab: the library, or one environment's page when the address says which
 * (`?environment=`). Making or changing an environment happens in a drawer over either of them.
 * Nothing here is kept in the Lab page: an environment, its versions and its pictures live on
 * the server.
 */
export function EnvironmentLabPanel() {
  const [openId, openEnvironment] = useOpenEnvironment();
  // `opened` is kept apart from the rest, so the drawer does not change its title while it
  // slides out.
  const [drawer, setDrawer] = useState<DrawerConfig>({ opened: false, environmentId: null });

  return (
    <>
      {openId === null ? (
        <EnvironmentLibrary
          onOpen={openEnvironment}
          onNew={() => setDrawer({ opened: true, environmentId: null })}
        />
      ) : (
        <EnvironmentPage
          environmentId={openId}
          onBack={() => openEnvironment(null)}
          onEdit={() => setDrawer({ opened: true, environmentId: openId })}
        />
      )}
      <EnvironmentDrawer
        opened={drawer.opened}
        onClose={() => setDrawer((current) => ({ ...current, opened: false }))}
        environmentId={drawer.environmentId}
        onSaved={(environment, created) => {
          setDrawer((current) => ({ ...current, opened: false }));
          if (created) {
            // The new environment's page opens, so its picture can be made next.
            openEnvironment(environment.id);
          }
        }}
      />
    </>
  );
}
