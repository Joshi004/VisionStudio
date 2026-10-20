import { Alert, Drawer, Loader, Title } from "@mantine/core";

import { useLibraryEnvironment, type LibraryEnvironment } from "../../api/environmentLab";
import { describeError } from "../../api/errors";
import { EnvironmentForm } from "./EnvironmentForm";

type DrawerBodyProps = {
  environmentId: number | null;
  onSaved: (environment: LibraryEnvironment, created: boolean) => void;
};

/** What is inside the drawer. It is shown only while the drawer is open, so it starts afresh. */
function DrawerBody({ environmentId, onSaved }: DrawerBodyProps) {
  const environment = useLibraryEnvironment(environmentId);

  if (environmentId === null) {
    return <EnvironmentForm environment={null} onSaved={onSaved} />;
  }
  if (environment.isLoading) {
    return <Loader size="sm" />;
  }
  if (environment.isError || !environment.data) {
    return (
      <Alert color="red" title="Could not load the environment">
        {describeError(environment.error)}
      </Alert>
    );
  }
  // Keyed by the version, so the form starts from the saved profile.
  return (
    <EnvironmentForm
      key={`${environment.data.id}-${environment.data.version}`}
      environment={environment.data}
      onSaved={onSaved}
    />
  );
}

type EnvironmentDrawerProps = {
  opened: boolean;
  onClose: () => void;
  /** The environment to edit, or null for a new one. */
  environmentId: number | null;
  /** An environment was saved. `created` is true for a new one. */
  onSaved: (environment: LibraryEnvironment, created: boolean) => void;
};

/** Making or changing an environment's profile in a drawer. */
export function EnvironmentDrawer({
  opened,
  onClose,
  environmentId,
  onSaved,
}: EnvironmentDrawerProps) {
  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      position="right"
      size="lg"
      title={
        <Title order={4} component="span">
          {environmentId === null ? "New environment" : "Edit environment"}
        </Title>
      }
    >
      <DrawerBody environmentId={environmentId} onSaved={onSaved} />
    </Drawer>
  );
}
