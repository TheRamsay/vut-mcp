import {
  Action,
  ActionPanel,
  Color,
  Icon,
  List,
  Toast,
  showToast,
} from "@raycast/api";
import { useEffect, useState } from "react";
import { runStudisPython } from "./studis";

type ChangeKind = "added" | "removed" | "updated";

type StudisChange = {
  kind: ChangeKind;
  resource_type: string;
  resource_id: string;
  title: string;
  course_code?: string;
  changed_fields: string[];
  before?: Record<string, unknown>;
  after?: Record<string, unknown>;
  detected_at: string;
};

type RecentChanges = {
  baseline_created: boolean;
  captured_at: string;
  changes: StudisChange[];
};

const PYTHON = String.raw`
import asyncio
import json

from vut_studis.client import StudisClient

async def main():
    changes = await StudisClient().get_recent_changes(force_refresh=True)
    print(json.dumps(changes.model_dump(mode="json"), ensure_ascii=False))

asyncio.run(main())
`;

export default function Command() {
  const [state, setState] = useState<{
    isLoading: boolean;
    changes?: RecentChanges;
    error?: string;
  }>({ isLoading: true });

  async function loadChanges() {
    setState((previous) => ({
      ...previous,
      isLoading: true,
      error: undefined,
    }));

    try {
      const changes = await runStudisPython<RecentChanges>(PYTHON);
      setState({ isLoading: false, changes });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setState({ isLoading: false, error: message });
      await showToast({
        style: Toast.Style.Failure,
        title: "Could not load VUT changes",
        message,
      });
    }
  }

  useEffect(() => {
    void loadChanges();
  }, []);

  if (state.error) {
    return (
      <List isLoading={state.isLoading}>
        <List.EmptyView
          icon={Icon.Warning}
          title="Could not load VUT Changes"
          description={state.error}
          actions={
            <ActionPanel>
              <Action
                title="Retry"
                icon={Icon.ArrowClockwise}
                onAction={loadChanges}
              />
            </ActionPanel>
          }
        />
      </List>
    );
  }

  const changes = state.changes;

  return (
    <List
      isLoading={state.isLoading}
      searchBarPlaceholder="Filter by course, type, field, or title..."
      navigationTitle="VUT Changes"
    >
      <List.EmptyView
        icon={changes?.baseline_created ? Icon.Clock : Icon.CheckCircle}
        title={emptyTitle(changes)}
        description={emptyDescription(changes)}
        actions={
          <ActionPanel>
            <Action
              title="Refresh Snapshot"
              icon={Icon.ArrowClockwise}
              onAction={loadChanges}
            />
          </ActionPanel>
        }
      />
      {changeSections(changes?.changes ?? []).map((section) => (
        <List.Section
          key={section.kind}
          title={`${section.title} (${section.changes.length})`}
        >
          {section.changes.map((change) => (
            <ChangeItem
              key={changeKey(change)}
              change={change}
              onRefresh={loadChanges}
            />
          ))}
        </List.Section>
      ))}
    </List>
  );
}

function ChangeItem({
  change,
  onRefresh,
}: {
  change: StudisChange;
  onRefresh: () => void;
}) {
  return (
    <List.Item
      icon={{
        source: changeIcon(change.kind),
        tintColor: changeColor(change.kind),
      }}
      title={change.title}
      subtitle={changeSubtitle(change)}
      accessories={[
        { text: change.resource_type.replaceAll("_", " ") },
        { text: formatDateTime(change.detected_at) },
      ]}
      keywords={[
        change.kind,
        change.resource_type,
        change.course_code ?? "",
        change.title,
        ...change.changed_fields,
      ]}
      actions={
        <ActionPanel>
          <Action.CopyToClipboard
            title="Copy Summary"
            content={copySummary(change)}
          />
          <Action
            title="Refresh Snapshot"
            icon={Icon.ArrowClockwise}
            onAction={onRefresh}
          />
        </ActionPanel>
      }
    />
  );
}

function changeSections(changes: StudisChange[]) {
  return [
    {
      kind: "added",
      title: "Added",
      changes: changes.filter((change) => change.kind === "added"),
    },
    {
      kind: "updated",
      title: "Updated",
      changes: changes.filter((change) => change.kind === "updated"),
    },
    {
      kind: "removed",
      title: "Removed",
      changes: changes.filter((change) => change.kind === "removed"),
    },
  ].filter((section) => section.changes.length > 0);
}

function changeSubtitle(change: StudisChange): string {
  const fields = change.changed_fields.join(", ");
  return [
    change.course_code,
    change.kind,
    fields ? `Fields: ${fields}` : undefined,
  ]
    .filter(Boolean)
    .join(" · ");
}

function changeKey(change: StudisChange): string {
  return [
    change.kind,
    change.resource_type,
    change.resource_id,
    change.detected_at,
  ].join(":");
}

function changeIcon(kind: ChangeKind): Icon {
  if (kind === "added") {
    return Icon.PlusCircle;
  }
  if (kind === "removed") {
    return Icon.MinusCircle;
  }
  return Icon.Pencil;
}

function changeColor(kind: ChangeKind): Color {
  if (kind === "added") {
    return Color.Green;
  }
  if (kind === "removed") {
    return Color.Red;
  }
  return Color.Blue;
}

function emptyTitle(changes: RecentChanges | undefined): string {
  if (changes?.baseline_created) {
    return "Baseline Created";
  }
  return "No Recent VUT Changes";
}

function emptyDescription(changes: RecentChanges | undefined): string {
  if (changes?.baseline_created) {
    return "The first snapshot was stored. Future refreshes will show changes.";
  }
  if (changes) {
    return `Snapshot checked at ${formatDateTime(changes.captured_at)}.`;
  }
  return "";
}

function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat("cs-CZ", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function copySummary(change: StudisChange): string {
  return [
    `[${change.kind}] ${change.title}`,
    `Type: ${change.resource_type}`,
    change.course_code ? `Course: ${change.course_code}` : undefined,
    change.changed_fields.length > 0
      ? `Changed fields: ${change.changed_fields.join(", ")}`
      : undefined,
    `Detected: ${formatDateTime(change.detected_at)}`,
  ]
    .filter(Boolean)
    .join("\n");
}
