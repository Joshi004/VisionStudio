import { useState } from "react";
import { ActionIcon, Alert, Button, Group, Menu, Modal, ScrollArea, Stack, Text, TextInput, NavLink } from "@mantine/core";

import { useDeleteChat, useRenameChat, type ChatSummary } from "../../api/chatLab";
import { describeError } from "../../api/errors";

type ChatListProps = {
  chats: ChatSummary[];
  /** Null while a new chat that has no message yet is open. */
  selectedId: number | null;
  onSelect: (chatId: number) => void;
  onNew: () => void;
  /** Called after a chat was deleted, with its id. */
  onDeleted: (chatId: number) => void;
};

/** The chats on the left: a new chat button, and for each chat a menu to rename or delete it. */
export function ChatList({ chats, selectedId, onSelect, onNew, onDeleted }: ChatListProps) {
  const rename = useRenameChat();
  const remove = useDeleteChat();
  const [renaming, setRenaming] = useState<ChatSummary | null>(null);
  const [title, setTitle] = useState("");
  const [deleting, setDeleting] = useState<ChatSummary | null>(null);

  function startRename(chat: ChatSummary) {
    rename.reset();
    setTitle(chat.title);
    setRenaming(chat);
  }

  function startDelete(chat: ChatSummary) {
    remove.reset();
    setDeleting(chat);
  }

  return (
    <Stack gap="xs">
      <Button variant="light" onClick={onNew}>
        New chat
      </Button>
      <ScrollArea h="55vh">
        <Stack gap={2}>
          {chats.length === 0 && (
            <Text size="sm" c="dimmed" p="xs">
              No chats yet.
            </Text>
          )}
          {chats.map((chat) => (
            <NavLink
              key={chat.id}
              label={chat.title}
              active={chat.id === selectedId}
              onClick={() => onSelect(chat.id)}
              rightSection={
                <Menu position="bottom-end" withinPortal>
                  <Menu.Target>
                    <ActionIcon
                      variant="subtle"
                      color="gray"
                      size="sm"
                      aria-label={`Options for ${chat.title}`}
                      onClick={(event) => event.stopPropagation()}
                    >
                      ⋯
                    </ActionIcon>
                  </Menu.Target>
                  <Menu.Dropdown>
                    <Menu.Item onClick={() => startRename(chat)}>Rename</Menu.Item>
                    <Menu.Item color="red" onClick={() => startDelete(chat)}>
                      Delete
                    </Menu.Item>
                  </Menu.Dropdown>
                </Menu>
              }
            />
          ))}
        </Stack>
      </ScrollArea>

      <Modal opened={renaming !== null} onClose={() => setRenaming(null)} title="Rename chat">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (renaming && title.trim() !== "") {
              rename.mutate(
                { chatId: renaming.id, title: title.trim() },
                { onSuccess: () => setRenaming(null) },
              );
            }
          }}
        >
          <Stack>
            <TextInput
              label="Title"
              value={title}
              onChange={(event) => setTitle(event.currentTarget.value)}
              data-autofocus
            />
            {rename.isError && (
              <Alert color="red" variant="light" p="xs">
                {describeError(rename.error)}
              </Alert>
            )}
            <Group justify="flex-end">
              <Button variant="default" onClick={() => setRenaming(null)}>
                Cancel
              </Button>
              <Button type="submit" loading={rename.isPending} disabled={title.trim() === ""}>
                Save
              </Button>
            </Group>
          </Stack>
        </form>
      </Modal>

      <Modal opened={deleting !== null} onClose={() => setDeleting(null)} title="Delete chat">
        <Stack>
          <Text>
            Delete “{deleting?.title}” and all its messages? This cannot be undone.
          </Text>
          {remove.isError && (
            <Alert color="red" variant="light" p="xs">
              {describeError(remove.error)}
            </Alert>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setDeleting(null)}>
              Cancel
            </Button>
            <Button
              color="red"
              loading={remove.isPending}
              onClick={() => {
                if (deleting) {
                  const chatId = deleting.id;
                  remove.mutate(chatId, {
                    onSuccess: () => {
                      setDeleting(null);
                      onDeleted(chatId);
                    },
                  });
                }
              }}
            >
              Delete
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
