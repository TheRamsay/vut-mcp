import {
  Action,
  ActionPanel,
  Color,
  Icon,
  List,
  getPreferenceValues,
} from "@raycast/api";
import { useMemo } from "react";
import { CourseDetail } from "./course-detail";
import { type Preferences } from "./studis";
import { useStudisData } from "./use-studis-data";

type TodayPreferences = Preferences & { horizonDays: string };

type PendingAction = {
  type: string;
  severity: "critical" | "warning" | "info";
  action_kind: string;
  course_code: string;
  course_name?: string;
  title: string;
  reason: string;
  suggested_next_step: string;
  detail?: string;
  due_at?: string;
  starts_at?: string;
  days_left?: number;
  detail_url?: string;
};

const PYTHON = String.raw`
import asyncio
import json
import sys

from vut_studis.client import StudisClient

horizon_days = int(sys.argv[1])

async def main():
    actions = await StudisClient().get_pending_actions(horizon_days=horizon_days)
    print(json.dumps([action.model_dump(mode="json") for action in actions], ensure_ascii=False))

asyncio.run(main())
`;

export default function Command() {
  const preferences = getPreferenceValues<TodayPreferences>();
  const horizonDays = Number.parseInt(preferences.horizonDays, 10);
  const resolvedHorizonDays = Number.isFinite(horizonDays) ? horizonDays : 7;
  const args = useMemo(
    () => [String(resolvedHorizonDays)],
    [resolvedHorizonDays],
  );
  const {
    isLoading,
    data: actions,
    error,
    reload,
  } = useStudisData<PendingAction[]>({
    python: PYTHON,
    args,
    initialData: [],
    failureTitle: "Could not load VUT actions",
  });

  if (error) {
    return (
      <List isLoading={isLoading}>
        <List.EmptyView
          icon={Icon.Warning}
          title="Could not load VUT Today"
          description={error}
          actions={
            <ActionPanel>
              <Action
                title="Retry"
                icon={Icon.ArrowClockwise}
                onAction={reload}
              />
            </ActionPanel>
          }
        />
      </List>
    );
  }

  return (
    <List
      isLoading={isLoading}
      searchBarPlaceholder="Filter by course, title, severity, or action..."
      navigationTitle="VUT Today"
    >
      <List.EmptyView
        icon={Icon.CheckCircle}
        title="No Pending VUT Actions"
        description={`No pending actions in the next ${resolvedHorizonDays} days.`}
        actions={
          <ActionPanel>
            <Action
              title="Refresh"
              icon={Icon.ArrowClockwise}
              onAction={reload}
            />
          </ActionPanel>
        }
      />
      {(["critical", "warning", "info"] as const).map((severity) => {
        const sectionActions = actions.filter(
          (action) => action.severity === severity,
        );
        if (sectionActions.length === 0) {
          return null;
        }

        return (
          <List.Section
            key={severity}
            title={sectionTitle(severity, sectionActions.length)}
          >
            {sectionActions.map((action) => (
              <ActionItem
                key={actionKey(action)}
                action={action}
                onRefresh={reload}
              />
            ))}
          </List.Section>
        );
      })}
    </List>
  );
}

function ActionItem({
  action,
  onRefresh,
}: {
  action: PendingAction;
  onRefresh: () => void;
}) {
  const date = action.due_at ?? action.starts_at;
  const detail = [action.course_name, action.reason]
    .filter(Boolean)
    .join(" · ");
  const accessories: List.Item.Accessory[] = [
    { text: action.action_kind.replaceAll("_", " ") },
    {
      text: daysLeftText(action.days_left),
      tooltip: date ? formatDateTime(date) : "No date",
    },
  ];

  return (
    <List.Item
      icon={{
        source: severityIcon(action.severity),
        tintColor: severityColor(action.severity),
      }}
      title={`${action.course_code}: ${action.title}`}
      subtitle={detail}
      accessories={accessories}
      keywords={[
        action.course_code,
        action.title,
        action.severity,
        action.action_kind,
        action.reason,
      ]}
      actions={
        <ActionPanel>
          <ActionPanel.Section>
            <Action.Push
              title="Show Course Detail"
              icon={Icon.Sidebar}
              target={
                <CourseDetail
                  courseCode={action.course_code}
                  fallbackTitle={`${action.course_code}: ${action.course_name ?? action.title}`}
                />
              }
            />
            {action.detail_url ? (
              <Action.OpenInBrowser
                title="Open in Studis"
                url={action.detail_url}
              />
            ) : null}
            <Action.CopyToClipboard
              title="Copy Summary"
              content={copySummary(action)}
            />
            <Action
              title="Refresh"
              icon={Icon.ArrowClockwise}
              onAction={onRefresh}
            />
          </ActionPanel.Section>
          <ActionPanel.Section>
            <Action.CopyToClipboard
              title="Copy Suggested Next Step"
              content={action.suggested_next_step}
            />
            <Action.CopyToClipboard
              title="Copy Reason"
              content={action.reason}
            />
          </ActionPanel.Section>
        </ActionPanel>
      }
    />
  );
}

function actionKey(action: PendingAction): string {
  return [
    action.type,
    action.course_code,
    action.title,
    action.due_at ?? "",
    action.starts_at ?? "",
  ].join(":");
}

function sectionTitle(
  severity: PendingAction["severity"],
  count: number,
): string {
  const label = severity.charAt(0).toUpperCase() + severity.slice(1);
  return `${label} (${count})`;
}

function severityIcon(severity: PendingAction["severity"]): Icon {
  if (severity === "critical") {
    return Icon.ExclamationMark;
  }
  if (severity === "warning") {
    return Icon.Warning;
  }
  return Icon.Info;
}

function severityColor(severity: PendingAction["severity"]): Color {
  if (severity === "critical") {
    return Color.Red;
  }
  if (severity === "warning") {
    return Color.Yellow;
  }
  return Color.Blue;
}

function daysLeftText(daysLeft: number | undefined): string {
  if (daysLeft === undefined || daysLeft === null) {
    return "No date";
  }
  if (daysLeft === 0) {
    return "Today";
  }
  if (daysLeft === 1) {
    return "Tomorrow";
  }
  if (daysLeft < 0) {
    return `${Math.abs(daysLeft)}d overdue`;
  }
  return `${daysLeft}d`;
}

function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat("cs-CZ", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function copySummary(action: PendingAction): string {
  const when = action.due_at ?? action.starts_at;
  return [
    `[${action.severity}] ${action.course_code}: ${action.title}`,
    when
      ? `When: ${formatDateTime(when)} (${daysLeftText(action.days_left)})`
      : "When: no date",
    `Action: ${action.action_kind}`,
    `Reason: ${action.reason}`,
    `Next: ${action.suggested_next_step}`,
    action.detail_url ? `Link: ${action.detail_url}` : undefined,
  ]
    .filter(Boolean)
    .join("\n");
}
