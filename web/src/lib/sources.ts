/** Where a task or goal came from (backend `TaskSource` / `GoalSource`). */
export type Source = "manual" | "conversation" | "email" | "calendar" | "notion";

export const SOURCES: Source[] = ["manual", "conversation", "email", "calendar", "notion"];

export const SOURCE_LABEL: Record<Source, string> = {
  manual: "Manual",
  conversation: "Chat",
  email: "Email",
  calendar: "Calendar",
  notion: "Notion",
};
