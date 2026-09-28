import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";
import { makeTask, sentBodies, serveGoals } from "@/test/goals-server";
import { navigation } from "@/test/navigation-mock";
import { renderWithProviders } from "@/test/render";
import { serveTasks } from "@/test/tasks-server";
import TaskCalendar from "./task-calendar";

// jsdom can't lay FullCalendar out, so it's replaced at the module boundary: the fake reports a
// fixed visible range (like FullCalendar's datesSet) and renders each event as a button.
const calendarProps = vi.hoisted(() => ({ last: {} as Record<string, unknown> }));

vi.mock("@fullcalendar/react", () => ({
  default: function FakeCalendar(props: {
    events: { id: string; extendedProps: unknown }[];
    datesSet: (info: unknown) => void;
    eventClick: (info: unknown) => void;
    eventContent: (info: unknown) => React.ReactNode;
    initialView: string;
  }) {
    calendarProps.last = props;
    useEffect(() => {
      props.datesSet({
        start: new Date("2026-08-30T00:00:00Z"),
        end: new Date("2026-10-11T00:00:00Z"),
        view: { currentStart: new Date("2026-09-01T00:00:00Z") },
      });
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
    return (
      <div>
        {props.events.map((event) => (
          <button key={event.id} onClick={() => props.eventClick({ event })}>
            {props.eventContent({ event })}
          </button>
        ))}
      </div>
    );
  },
  useCalendarController: () => ({
    changeView: vi.fn(),
    prev: vi.fn(),
    next: vi.fn(),
    today: vi.fn(),
    view: { title: "September 2026" },
  }),
}));
vi.mock("@fullcalendar/react/daygrid", () => ({ default: {} }));
vi.mock("@fullcalendar/react/list", () => ({ default: {} }));
vi.mock("@fullcalendar/react/themes/classic", () => ({ default: {} }));

const originalMatchMedia = window.matchMedia;
afterEach(() => {
  window.matchMedia = originalMatchMedia;
});

function renderCalendar(onOpen = vi.fn()) {
  navigation.pathname = "/tasks";
  navigation.search = "view=calendar";
  renderWithProviders(
    <TooltipProvider>
      <TaskCalendar
        filters={{ status: "open", source: "email", urgency: null }}
        mode="month"
        date={null}
        onOpen={onOpen}
        onNavigate={vi.fn()}
      />
    </TooltipProvider>,
  );
  return onOpen;
}

describe("task calendar", () => {
  it("asks for the visible range with the filters, following every page", async () => {
    serveGoals();
    serveTasks(
      ...Array.from({ length: 150 }, (_, i) => makeTask({ title: `Mail task ${i}`, source: "email", due_date: "2026-09-15" })),
      makeTask({ title: "Out of range", source: "email", due_date: "2026-12-01" }),
    );
    renderCalendar();

    await waitFor(() => expect(sentBodies("GET /tasks")).toHaveLength(2));
    const [first, second] = sentBodies("GET /tasks").map((search) => new URLSearchParams(search as string));
    expect(first.get("due_from")).toBe("2026-08-30");
    expect(first.get("due_to")).toBe("2026-10-10");
    expect(first.get("status")).toBe("open");
    expect(first.get("source")).toBe("email");
    expect(first.get("items_per_page")).toBe("100");
    expect(second.get("page")).toBe("2");
    expect(await screen.findAllByRole("button", { name: /^Mail task/ })).toHaveLength(150);
    expect(screen.queryByText("Out of range")).not.toBeInTheDocument();
  }, 20_000); // 150 events are slow to render in jsdom

  it("opens a task when its event is clicked, with a descriptive name", async () => {
    serveGoals();
    const task = makeTask({ title: "Send proposal", source: "email", due_date: "2026-10-02", urgency: "high" });
    serveTasks(task);
    const onOpen = renderCalendar();

    const event = await screen.findByRole("button", { name: /Send proposal/ });
    expect(within(event).getByLabelText("Send proposal, due Fri 2 Oct, high urgency")).toBeInTheDocument();
    await userEvent.click(event);

    expect(onOpen).toHaveBeenCalledWith(task.id);
  });

  it("uses the month grid, with the Month/Week switch, on desktop", async () => {
    serveGoals();
    serveTasks();
    renderCalendar();
    await waitFor(() => expect(calendarProps.last.initialView).toBe("dayGridMonth"));
    expect(screen.getByLabelText("Calendar range")).toBeInTheDocument();
  });

  it("shows a week agenda without the Month/Week switch on phones", async () => {
    window.matchMedia = ((query: string) => ({
      ...originalMatchMedia(query),
      matches: false,
    })) as typeof window.matchMedia;
    serveGoals();
    serveTasks();
    renderCalendar();

    await waitFor(() => expect(calendarProps.last.initialView).toBe("listWeek"));
    expect(screen.queryByLabelText("Calendar range")).not.toBeInTheDocument();
    expect(await screen.findByText("No tasks due in this period.")).toBeInTheDocument();
  });
});
