"use client";

// Loaded only when the Calendar view opens (next/dynamic in tasks-view.tsx), together with its CSS.
import FullCalendar, { useCalendarController, type DatesSetInfo, type EventDisplayInfo } from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/react/daygrid";
import listPlugin from "@fullcalendar/react/list";
import classicThemePlugin from "@fullcalendar/react/themes/classic";
import { ChevronLeftIcon, ChevronRightIcon } from "lucide-react";
import { useEffect, useState } from "react";

import "@fullcalendar/react/skeleton.css";
import "@fullcalendar/react/themes/classic/theme.css";
import "./task-calendar.css";

import { Button } from "@/components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useTimeZone } from "@/lib/auth/use-session";
import { addDays, formatDay, todayIn } from "@/lib/format/date";
import { URGENCY_LABEL, type Task, type TaskFilters } from "@/lib/tasks/labels";
import { useCalendarTasks } from "@/lib/tasks/queries";
import { useMediaQuery } from "@/lib/use-media-query";
import { cn } from "@/lib/utils";

export type CalendarMode = "month" | "week";

type TaskCalendarProps = {
  filters: TaskFilters;
  mode: CalendarMode;
  /** A day to show (`YYYY-MM-DD`); `null` = today. */
  date: string | null;
  onOpen: (id: string) => void;
  onNavigate: (changes: { cal?: CalendarMode; date?: string }) => void;
};

/**
 * Plan §1.1–§1.2: due dates as all-day items. Desktop: month or week grid; phone: a week agenda.
 * Read-only; busy days collapse to "+N more". The toolbar is ours so it matches the list's controls.
 */
export default function TaskCalendar({ filters, mode, date, onOpen, onNavigate }: TaskCalendarProps) {
  const desktop = useMediaQuery("(min-width: 768px)");
  const timeZone = useTimeZone();
  const controller = useCalendarController();
  const [range, setRange] = useState<{ from: string; to: string } | null>(null);
  const view = desktop ? (mode === "week" ? "dayGridWeek" : "dayGridMonth") : "listWeek";

  useEffect(() => {
    controller.changeView(view);
  }, [controller, view]);

  const calendar = useCalendarTasks(range ?? { from: "", to: "" }, filters, range !== null);
  const events = (calendar.data?.tasks ?? []).map((task) => ({
    id: task.id,
    title: task.title,
    start: task.due_date!,
    allDay: true,
    extendedProps: { task },
  }));

  const onDatesSet = (info: DatesSetInfo) => {
    const from = todayIn(timeZone, info.start);
    const to = addDays(todayIn(timeZone, info.end), -1);
    setRange((current) => (current?.from === from && current.to === to ? current : { from, to }));
    // Keep the URL's date in step with ‹ › navigation, but leave it out while the view shows today.
    const shown = todayIn(timeZone, info.view.currentStart);
    const today = todayIn(timeZone);
    const showsToday = from <= today && today <= to;
    if (shown !== date && !(date === null && showsToday)) onNavigate({ date: shown });
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1">
          <Button variant="outline" size="icon" aria-label="Previous" onClick={() => controller.prev()}>
            <ChevronLeftIcon aria-hidden />
          </Button>
          <Button variant="outline" size="icon" aria-label="Next" onClick={() => controller.next()}>
            <ChevronRightIcon aria-hidden />
          </Button>
          <Button variant="outline" onClick={() => controller.today()}>
            Today
          </Button>
        </div>
        <h2 aria-live="polite" className="font-serif text-title font-medium">
          {controller.view?.title}
        </h2>
        {desktop && (
          <ToggleGroup
            type="single"
            value={mode}
            onValueChange={(value) => value && onNavigate({ cal: value as CalendarMode })}
            aria-label="Calendar range"
            className="ml-auto"
          >
            <ToggleGroupItem value="month">Month</ToggleGroupItem>
            <ToggleGroupItem value="week">Week</ToggleGroupItem>
          </ToggleGroup>
        )}
      </div>
      {calendar.data?.capped && <p className="text-sm text-ink-2">Showing the first 1,000 tasks.</p>}
      {calendar.data && calendar.data.tasks.length === 0 && (
        <p className="text-sm text-ink-2">No tasks due in this period.</p>
      )}
      <div className="task-calendar">
        <FullCalendar
          plugins={[dayGridPlugin, listPlugin, classicThemePlugin]}
          controller={controller}
          initialView={view}
          initialDate={date ?? undefined}
          timeZone={timeZone}
          headerToolbar={false}
          height="auto"
          editable={false}
          eventInteractive
          dayMaxEvents
          events={events}
          datesSet={onDatesSet}
          eventClick={(info) => onOpen(info.event.id)}
          eventContent={(info: EventDisplayInfo) => <CalendarEvent task={info.event.extendedProps.task as Task} />}
          noEventsText="No tasks due this week."
        />
      </div>
    </div>
  );
}

/** Title plus a red dot for high urgency; done tasks faded and struck through (plan §4). */
function CalendarEvent({ task }: { task: Task }) {
  const timeZone = useTimeZone();
  const done = task.status === "done";
  const label = [task.title, `due ${formatDay(task.due_date!, timeZone)}`, task.urgency === "high" && "high urgency", done && "done"]
    .filter(Boolean)
    .join(", ");

  return (
    <span aria-label={label} className={cn("flex min-w-0 items-center gap-1.5", done && "opacity-60")}>
      {task.urgency === "high" && (
        <span aria-hidden title={`${URGENCY_LABEL.high} urgency`} className="size-2 shrink-0 rounded-full bg-danger" />
      )}
      <span className={cn("truncate", done && "line-through")}>{task.title}</span>
    </span>
  );
}
