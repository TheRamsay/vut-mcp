import { Action, ActionPanel, Color, Detail, Icon } from "@raycast/api";
import { useMemo } from "react";
import { useStudisData } from "./use-studis-data";

type Grade = {
  course_code?: string;
  course_name: string;
  grade?: "A" | "B" | "C" | "D" | "E" | "F";
  grade_awarded_on?: string;
  academic_year?: string;
  semester?: string;
  credits?: number;
  completion?: string;
  credit_awarded?: boolean;
  credit_awarded_on?: string;
  points?: number;
  exam_term?: number;
  absolved?: boolean;
};

type AssessmentItem = {
  order?: number;
  name: string;
  category?: string;
  min_points?: number;
  min_points_for_admission?: number;
  max_points?: number;
  points?: number;
  fulfilled?: boolean;
  message_url?: string;
  notes?: string[];
  entries?: AssessmentEntry[];
};

type AssessmentEntry = {
  name: string;
  order?: number;
  points?: number;
  fulfilled?: boolean;
  awarded_on?: string;
  message_url?: string;
};

type CourseTerm = {
  assessment_name?: string;
  term_number?: number;
  name: string;
  note?: string;
  starts_at?: string;
  room?: string;
  registered?: boolean;
  capacity_used?: number;
  capacity_total?: number;
  registration_opens_at?: string;
  registration_closes_at?: string;
  can_register?: boolean;
  can_unregister?: boolean;
  max_points?: number;
  earned_points?: number;
  detail_url?: string;
};

type CourseAssignment = {
  assessment_name?: string;
  assignment_number?: number;
  name: string;
  teacher?: string;
  submit_until?: string;
  registered?: boolean;
  can_register?: boolean;
  submitted?: boolean;
  submitted_files?: { name: string; uploaded_at?: string }[];
  detail_url?: string;
};

type PendingAction = {
  severity: "critical" | "warning" | "info";
  action_kind: string;
  course_code: string;
  title: string;
  reason: string;
  suggested_next_step: string;
  due_at?: string;
  starts_at?: string;
  days_left?: number;
  detail_url?: string;
};

type CourseNote = {
  body: string;
  updated_at: string;
};

type CourseStatus = {
  course_code: string;
  course_name?: string;
  grades: Grade[];
  assessment?: { items: AssessmentItem[] };
  terms?: { terms: CourseTerm[] };
  assignments?: { assignments: CourseAssignment[] };
  pending_actions: PendingAction[];
  course_notes: CourseNote[];
  summary: string[];
  detail_url?: string;
};

const PYTHON = String.raw`
import asyncio
import json
import sys

from vut_studis.client import StudisClient

course_code = sys.argv[1]

async def main():
    client = StudisClient()
    status = await client.get_course_status(course_code, mode="full")
    data = status.model_dump(mode="json")
    data["detail_url"] = (await client.get_course_detail_urls([course_code])).get(course_code)
    print(json.dumps(data, ensure_ascii=False))

asyncio.run(main())
`;

export function CourseDetail({
  courseCode,
  fallbackTitle,
}: {
  courseCode: string;
  fallbackTitle?: string;
}) {
  const args = useMemo(() => [courseCode], [courseCode]);
  const { isLoading, data, error, reload } = useStudisData<CourseStatus | null>(
    {
      python: PYTHON,
      args,
      initialData: null,
      failureTitle: "Could not load course detail",
    },
  );

  const title = data?.course_name
    ? `${data.course_code}: ${data.course_name}`
    : (fallbackTitle ?? courseCode);

  if (error) {
    return (
      <Detail
        isLoading={isLoading}
        navigationTitle={title}
        markdown={`# Could not load course detail\n\n${escapeMarkdown(error)}`}
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
    );
  }

  return (
    <Detail
      isLoading={isLoading}
      navigationTitle={title}
      markdown={data ? courseMarkdown(data) : "# Loading Course Detail"}
      metadata={data ? courseMetadata(data) : undefined}
      actions={
        <ActionPanel>
          <ActionPanel.Section>
            <Action
              title="Refresh"
              icon={Icon.ArrowClockwise}
              onAction={reload}
            />
            {data?.detail_url ? (
              <Action.OpenInBrowser
                title="Open in Studis"
                url={data.detail_url}
              />
            ) : null}
            {data ? (
              <Action.CopyToClipboard
                title="Copy Course Summary"
                content={copyCourseSummary(data)}
              />
            ) : null}
          </ActionPanel.Section>
        </ActionPanel>
      }
    />
  );
}

function courseMetadata(status: CourseStatus) {
  const grade = primaryGrade(status.grades);
  return (
    <Detail.Metadata>
      <Detail.Metadata.Label title="Course" text={status.course_code} />
      <Detail.Metadata.Label
        title="Points"
        text={pointsText(grade?.points)}
        icon={{ source: Icon.BarChart, tintColor: Color.Blue }}
      />
      <Detail.Metadata.Label
        title="Grade"
        text={grade?.grade ?? "Not awarded"}
        icon={{ source: gradeIcon(grade), tintColor: gradeColor(grade) }}
      />
      <Detail.Metadata.Label
        title="Credit"
        text={creditText(grade)}
        icon={{
          source: grade?.credit_awarded ? Icon.CheckCircle : Icon.Circle,
          tintColor: grade?.credit_awarded ? Color.Green : Color.SecondaryText,
        }}
      />
      <Detail.Metadata.Separator />
      <Detail.Metadata.Label
        title="Pending"
        text={String(status.pending_actions.length)}
        icon={{
          source: status.pending_actions.length > 0 ? Icon.Warning : Icon.Check,
          tintColor:
            status.pending_actions.length > 0 ? Color.Yellow : Color.Green,
        }}
      />
      <Detail.Metadata.Label
        title="Assignments"
        text={String(status.assignments?.assignments.length ?? 0)}
      />
      <Detail.Metadata.Label
        title="Terms"
        text={String(status.terms?.terms.length ?? 0)}
      />
      <Detail.Metadata.Label
        title="Notes"
        text={String(status.course_notes.length)}
      />
    </Detail.Metadata>
  );
}

function courseMarkdown(status: CourseStatus): string {
  return [
    `# ${escapeMarkdown(status.course_code)}${status.course_name ? ` - ${escapeMarkdown(status.course_name)}` : ""}`,
    summaryBlock(status),
    pendingActionsBlock(status.pending_actions),
    assessmentBlock(status.assessment?.items ?? []),
    termsBlock(status.terms?.terms ?? []),
    assignmentsBlock(status.assignments?.assignments ?? []),
    notesBlock(status.course_notes),
  ]
    .filter(Boolean)
    .join("\n\n");
}

function summaryBlock(status: CourseStatus): string {
  const grade = primaryGrade(status.grades);
  return [
    "## Overview",
    table([
      ["Points", pointsText(grade?.points)],
      ["Grade", grade?.grade ?? "Not awarded"],
      ["Credit", creditText(grade)],
      ["Completion", completionLabel(grade?.completion)],
      ["Semester", grade?.semester ?? "Unknown"],
      [
        "Credits",
        grade?.credits === undefined ? "Unknown" : formatNumber(grade.credits),
      ],
    ]),
    status.summary.length > 0
      ? status.summary.map((line) => `- ${escapeMarkdown(line)}`).join("\n")
      : "",
  ]
    .filter(Boolean)
    .join("\n\n");
}

function pendingActionsBlock(actions: PendingAction[]): string {
  if (actions.length === 0) {
    return "## Actions\n\nNo pending actions found.";
  }

  return [
    "## Actions",
    ...actions.map((action) =>
      [
        `### ${severityBadge(action.severity)} ${escapeMarkdown(action.title)}`,
        table([
          ["When", actionTime(action)],
          ["Action", action.action_kind.replaceAll("_", " ")],
          ["Reason", action.reason],
          ["Next", action.suggested_next_step],
        ]),
      ].join("\n\n"),
    ),
  ].join("\n\n");
}

function assessmentBlock(items: AssessmentItem[]): string {
  if (items.length === 0) {
    return "";
  }

  const rows = items.map((item) => [
    item.name,
    pointsRange(item.points, item.min_points, item.max_points),
    item.fulfilled === undefined ? "Unknown" : item.fulfilled ? "Yes" : "No",
  ]);

  return [
    "## Assessment",
    markdownTable(["Item", "Points", "Fulfilled"], rows),
    ...items
      .filter((item) => item.entries && item.entries.length > 0)
      .slice(0, 6)
      .map((item) => assessmentEntriesBlock(item)),
  ].join("\n\n");
}

function assessmentEntriesBlock(item: AssessmentItem): string {
  const rows = (item.entries ?? []).map((entry) => [
    entry.name,
    pointsText(entry.points),
    entry.awarded_on ? formatDate(entry.awarded_on) : "",
  ]);
  return `### ${escapeMarkdown(item.name)}\n\n${markdownTable(["Entry", "Points", "Date"], rows)}`;
}

function termsBlock(terms: CourseTerm[]): string {
  if (terms.length === 0) {
    return "";
  }

  const rows = terms.map((term) => [
    term.name,
    term.starts_at ? formatDateTime(term.starts_at) : "No date",
    term.registered === undefined ? "Unknown" : term.registered ? "Yes" : "No",
    term.can_register ? "Open" : "",
    term.room ?? "",
  ]);

  return [
    "## Terms",
    markdownTable(["Term", "When", "Registered", "Registration", "Room"], rows),
  ].join("\n\n");
}

function assignmentsBlock(assignments: CourseAssignment[]): string {
  if (assignments.length === 0) {
    return "";
  }

  const rows = assignments.map((assignment) => [
    assignment.name,
    assignment.submit_until
      ? formatDateTime(assignment.submit_until)
      : "No deadline",
    assignment.registered === undefined
      ? "Unknown"
      : assignment.registered
        ? "Yes"
        : "No",
    assignment.submitted === undefined
      ? "Unknown"
      : assignment.submitted
        ? "Yes"
        : "No",
  ]);

  return [
    "## Assignments",
    markdownTable(["Assignment", "Deadline", "Registered", "Submitted"], rows),
  ].join("\n\n");
}

function notesBlock(notes: CourseNote[]): string {
  if (notes.length === 0) {
    return "";
  }

  return [
    "## Local Notes",
    ...notes.map(
      (note) =>
        `- ${escapeMarkdown(note.body)} _(${formatDate(note.updated_at)})_`,
    ),
  ].join("\n");
}

function primaryGrade(grades: Grade[]): Grade | undefined {
  return [...grades].sort((left, right) => {
    const leftDate = left.grade_awarded_on ?? left.credit_awarded_on ?? "";
    const rightDate = right.grade_awarded_on ?? right.credit_awarded_on ?? "";
    return rightDate.localeCompare(leftDate);
  })[0];
}

function table(rows: [string, string][]): string {
  return markdownTable(["Field", "Value"], rows);
}

function markdownTable(headers: string[], rows: string[][]): string {
  return [
    `| ${headers.map(escapeMarkdown).join(" | ")} |`,
    `| ${headers.map(() => "---").join(" | ")} |`,
    ...rows.map(
      (row) =>
        `| ${row.map((cell) => escapeMarkdown(cell || " ")).join(" | ")} |`,
    ),
  ].join("\n");
}

function pointsRange(
  points: number | undefined,
  min: number | undefined,
  max: number | undefined,
): string {
  const current = pointsText(points);
  const limits = [
    min === undefined ? undefined : `min ${formatNumber(min)}`,
    max === undefined ? undefined : `max ${formatNumber(max)}`,
  ]
    .filter(Boolean)
    .join(", ");
  return limits ? `${current} (${limits})` : current;
}

function pointsText(points: number | undefined): string {
  if (points === undefined || points === null) {
    return "Unknown";
  }
  return `${formatNumber(points)} pts`;
}

function creditText(grade: Grade | undefined): string {
  if (grade?.credit_awarded === true) {
    return "Awarded";
  }
  if (grade?.credit_awarded === false) {
    return "Not awarded";
  }
  return "Unknown";
}

function completionLabel(completion: string | undefined): string {
  if (!completion) {
    return "Unknown";
  }
  return completion.replaceAll("_", " ");
}

function actionTime(action: PendingAction): string {
  const value = action.due_at ?? action.starts_at;
  if (!value) {
    return "No date";
  }
  const days =
    action.days_left === undefined
      ? ""
      : ` (${daysLeftText(action.days_left)})`;
  return `${formatDateTime(value)}${days}`;
}

function daysLeftText(daysLeft: number): string {
  if (daysLeft === 0) {
    return "today";
  }
  if (daysLeft === 1) {
    return "tomorrow";
  }
  if (daysLeft < 0) {
    return `${Math.abs(daysLeft)}d overdue`;
  }
  return `${daysLeft}d left`;
}

function severityBadge(severity: PendingAction["severity"]): string {
  if (severity === "critical") {
    return "Critical";
  }
  if (severity === "warning") {
    return "Warning";
  }
  return "Info";
}

function gradeIcon(grade: Grade | undefined): Icon {
  if (grade?.grade === "F") {
    return Icon.XMarkCircle;
  }
  if (grade?.grade || grade?.absolved) {
    return Icon.CheckCircle;
  }
  return Icon.Circle;
}

function gradeColor(grade: Grade | undefined): Color {
  if (grade?.grade === "F") {
    return Color.Red;
  }
  if (grade?.grade || grade?.absolved) {
    return Color.Green;
  }
  return Color.SecondaryText;
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("cs-CZ", {
    maximumFractionDigits: 2,
  }).format(value);
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("cs-CZ", {
    dateStyle: "medium",
  }).format(new Date(value));
}

function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat("cs-CZ", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function copyCourseSummary(status: CourseStatus): string {
  const grade = primaryGrade(status.grades);
  return [
    `${status.course_code}: ${status.course_name ?? "Course"}`,
    `Points: ${pointsText(grade?.points)}`,
    `Grade: ${grade?.grade ?? "not awarded"}`,
    `Credit: ${creditText(grade)}`,
    `Pending actions: ${status.pending_actions.length}`,
    status.detail_url ? `Link: ${status.detail_url}` : undefined,
  ]
    .filter(Boolean)
    .join("\n");
}

function escapeMarkdown(value: string): string {
  return value.replaceAll("|", "\\|").replaceAll("\n", " ");
}
