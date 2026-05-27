import { Action, ActionPanel, Color, Icon, List } from "@raycast/api";
import { useCallback } from "react";
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
  detail_url?: string;
};

const PYTHON = String.raw`
import asyncio
import json

from vut_studis.client import StudisClient

async def main():
    client = StudisClient()
    grades = await client.get_grades()
    detail_urls = await client.get_course_detail_urls(
        [grade.course_code for grade in grades if grade.course_code]
    )
    payload = []
    for grade in grades:
        data = grade.model_dump(mode="json")
        data["detail_url"] = detail_urls.get(grade.course_code)
        payload.append(data)
    print(json.dumps(payload, ensure_ascii=False))

asyncio.run(main())
`;

export default function Command() {
  const sortLoadedGrades = useCallback(sortGrades, []);
  const {
    isLoading,
    data: grades,
    error,
    reload,
  } = useStudisData<Grade[]>({
    python: PYTHON,
    initialData: [],
    failureTitle: "Could not load VUT grades",
    transform: sortLoadedGrades,
  });

  if (error) {
    return (
      <List isLoading={isLoading}>
        <List.EmptyView
          icon={Icon.Warning}
          title="Could not load VUT Grades"
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
      searchBarPlaceholder="Filter by course, points, grade, or semester..."
      navigationTitle="VUT Grades"
    >
      <List.EmptyView
        icon={Icon.List}
        title="No Grades Found"
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
      {gradeSections(grades).map((section) => (
        <List.Section
          key={section.title}
          title={`${section.title} (${section.grades.length})`}
        >
          {section.grades.map((grade) => (
            <GradeItem key={gradeKey(grade)} grade={grade} onRefresh={reload} />
          ))}
        </List.Section>
      ))}
    </List>
  );
}

function GradeItem({
  grade,
  onRefresh,
}: {
  grade: Grade;
  onRefresh: () => void;
}) {
  const code = grade.course_code ?? "Course";
  const subtitle = [
    grade.course_name,
    completionLabel(grade.completion),
    grade.semester,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <List.Item
      icon={{ source: gradeIcon(grade), tintColor: gradeColor(grade) }}
      title={`${code}: ${pointsText(grade.points)}`}
      subtitle={subtitle}
      accessories={gradeAccessories(grade)}
      keywords={[
        code,
        grade.course_name,
        grade.grade ?? "",
        grade.semester ?? "",
        grade.academic_year ?? "",
        String(grade.points ?? ""),
      ]}
      actions={
        <ActionPanel>
          <ActionPanel.Section>
            {grade.detail_url ? (
              <Action.OpenInBrowser
                title="Open in Studis"
                url={grade.detail_url}
              />
            ) : null}
            <Action.CopyToClipboard
              title="Copy Summary"
              content={copySummary(grade)}
            />
            {grade.course_code ? (
              <Action.CopyToClipboard
                title="Copy Course Code"
                content={grade.course_code}
              />
            ) : null}
          </ActionPanel.Section>
          <ActionPanel.Section>
            <Action
              title="Refresh"
              icon={Icon.ArrowClockwise}
              onAction={onRefresh}
            />
          </ActionPanel.Section>
        </ActionPanel>
      }
    />
  );
}

function sortGrades(grades: Grade[]): Grade[] {
  return [...grades].sort((left, right) => {
    const leftDone = left.absolved ? 1 : 0;
    const rightDone = right.absolved ? 1 : 0;
    if (leftDone !== rightDone) {
      return leftDone - rightDone;
    }

    return (left.course_code ?? left.course_name).localeCompare(
      right.course_code ?? right.course_name,
      "cs",
    );
  });
}

function gradeSections(grades: Grade[]) {
  const active = grades.filter((grade) => !grade.absolved);
  const completed = grades.filter((grade) => grade.absolved);
  return [
    { title: "Active", grades: active },
    { title: "Completed", grades: completed },
  ].filter((section) => section.grades.length > 0);
}

function gradeKey(grade: Grade): string {
  return [
    grade.academic_year ?? "",
    grade.semester ?? "",
    grade.course_code ?? "",
    grade.course_name,
  ].join(":");
}

function gradeIcon(grade: Grade): Icon {
  if (grade.grade === "F") {
    return Icon.XMarkCircle;
  }
  if (grade.grade) {
    return Icon.CheckCircle;
  }
  if (grade.credit_awarded) {
    return Icon.Check;
  }
  return Icon.Circle;
}

function gradeColor(grade: Grade): Color {
  if (grade.grade === "F") {
    return Color.Red;
  }
  if (grade.grade || grade.absolved) {
    return Color.Green;
  }
  if (grade.points !== undefined && grade.points !== null) {
    return Color.Blue;
  }
  return Color.SecondaryText;
}

function gradeAccessories(grade: Grade): List.Item.Accessory[] {
  return [
    { text: grade.grade ? `Grade ${grade.grade}` : "No grade" },
    { text: creditText(grade) },
    { text: creditsText(grade.credits) },
  ].filter((accessory) => accessory.text !== "");
}

function pointsText(points: number | undefined): string {
  if (points === undefined || points === null) {
    return "No points";
  }
  return `${formatNumber(points)} pts`;
}

function creditsText(credits: number | undefined): string {
  if (credits === undefined || credits === null) {
    return "";
  }
  return `${formatNumber(credits)} cr`;
}

function creditText(grade: Grade): string {
  if (grade.credit_awarded === true) {
    return "Credit yes";
  }
  if (grade.credit_awarded === false) {
    return "Credit no";
  }
  return "";
}

function completionLabel(completion: string | undefined): string {
  if (!completion) {
    return "";
  }
  return completion.replaceAll("_", " ");
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("cs-CZ", {
    maximumFractionDigits: 2,
  }).format(value);
}

function formatDate(value: string | undefined): string {
  if (!value) {
    return "";
  }
  return new Intl.DateTimeFormat("cs-CZ", {
    dateStyle: "medium",
  }).format(new Date(value));
}

function copySummary(grade: Grade): string {
  return [
    `${grade.course_code ?? "Course"}: ${grade.course_name}`,
    `Points: ${pointsText(grade.points)}`,
    `Grade: ${grade.grade ?? "not awarded"}`,
    `Credit: ${creditText(grade) || "not recorded"}`,
    grade.grade_awarded_on
      ? `Grade awarded: ${formatDate(grade.grade_awarded_on)}`
      : undefined,
    grade.credit_awarded_on
      ? `Credit awarded: ${formatDate(grade.credit_awarded_on)}`
      : undefined,
    grade.completion
      ? `Completion: ${completionLabel(grade.completion)}`
      : undefined,
    grade.semester ? `Semester: ${grade.semester}` : undefined,
    grade.detail_url ? `Link: ${grade.detail_url}` : undefined,
  ]
    .filter(Boolean)
    .join("\n");
}
