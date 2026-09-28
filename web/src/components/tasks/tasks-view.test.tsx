import { onlineManager, useQueryClient } from "@tanstack/react-query";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { LinkedTasks } from "@/components/goals/linked-tasks";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { addDays, todayIn } from "@/lib/format/date";
import { useDeleteGoal } from "@/lib/goals/queries";
import { goalsDb, makeGoal, makeTask, sentBodies, serveGoals } from "@/test/goals-server";
import { navigation } from "@/test/navigation-mock";
import { renderWithProviders } from "@/test/render";
import { user } from "@/test/server";
import { serveTasks } from "@/test/tasks-server";
import { TasksView } from "./tasks-view";

const today = todayIn(user.timezone);

function renderTasks(search = "", extra?: React.ReactNode) {
  navigation.pathname = "/tasks";
  navigation.search = search;
  return renderWithProviders(
    <TooltipProvider>
      <TasksView />
      {extra}
      <Toaster />
    </TooltipProvider>,
  );
}

const panel = () => screen.findByRole("dialog");
const lastQuery = () => new URLSearchParams(sentBodies("GET /tasks").at(-1) as string);

async function pick(trigger: RegExp | string, option: string) {
  await userEvent.click(screen.getByRole("combobox", { name: trigger }));
  await userEvent.click(await screen.findByRole("option", { name: option }));
}

afterEach(() => {
  act(() => onlineManager.setOnline(true));
});

describe("task list", () => {
  it("asks for open tasks, 50 at a time, grouped by when they're due", async () => {
    serveGoals();
    serveTasks(
      makeTask({ title: "Later one", due_date: addDays(today, 20) }),
      makeTask({ title: "Late one", due_date: addDays(today, -2) }),
      makeTask({ title: "Today one", due_date: today }),
      makeTask({ title: "Undated one" }),
      makeTask({ title: "Soon one", due_date: addDays(today, 3) }),
      makeTask({ title: "Tomorrow one", due_date: addDays(today, 1) }),
    );
    renderTasks();

    expect(screen.getByLabelText("Loading tasks")).toBeInTheDocument();
    const headings = await screen.findAllByRole("heading", { level: 3 });
    expect(headings.map((h) => h.textContent)).toEqual(["Overdue", "Today", "Tomorrow", "Next 7 days", "Later", "No date"]);
    expect(within(screen.getByRole("list", { name: "Overdue" })).getByText(/^Overdue · /)).toHaveClass("text-danger");
    expect(lastQuery().get("status")).toBe("open");
    expect(lastQuery().get("items_per_page")).toBe("50");
  });

  it("has no due headings in Done and All", async () => {
    serveGoals();
    serveTasks(makeTask({ title: "Finished", status: "done", due_date: today }));
    renderTasks("status=done");

    expect(await within(await screen.findByRole("list", { name: "Tasks" })).findByText("Finished")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 3 })).not.toBeInTheDocument();
  });

  it("filters by status, source and urgency through the URL, and clears", async () => {
    serveGoals();
    serveTasks(
      makeTask({ title: "From email", source: "email", urgency: "high" }),
      makeTask({ title: "Typed in", source: "manual", urgency: "low" }),
    );
    renderTasks();
    await screen.findByText("From email");

    await pick(/^Source:/, "Email");
    expect(navigation.replace).toHaveBeenLastCalledWith("/tasks?source=email");
    await waitFor(() => expect(screen.queryByText("Typed in")).not.toBeInTheDocument());
    expect(lastQuery().get("source")).toBe("email");

    await pick(/^Urgency:/, "High");
    expect(navigation.replace).toHaveBeenLastCalledWith("/tasks?source=email&urgency=high");

    await userEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(navigation.replace).toHaveBeenLastCalledWith("/tasks");
    expect(await screen.findByText("Typed in")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("radio", { name: "All" }));
    expect(navigation.replace).toHaveBeenLastCalledWith("/tasks?status=all");
    await waitFor(() => expect(lastQuery().has("status")).toBe(false));
  });

  it("loads the next page on request", async () => {
    serveGoals();
    serveTasks(...Array.from({ length: 51 }, (_, i) => makeTask({ title: `Task number ${i + 1}` })));
    renderTasks("status=all");
    const list = await screen.findByRole("list", { name: "Tasks" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(50);

    await userEvent.click(screen.getByRole("button", { name: "Load more" }));

    await waitFor(() => expect(within(list).getAllByRole("listitem")).toHaveLength(51));
  }, 20_000); // 51 rows are slow to render in jsdom

  it.each([
    ["", "A clear list.", "New task"],
    ["status=done", "Nothing finished yet.", null],
    ["source=email", "No tasks match these filters.", "Clear filters"],
  ])("shows the empty state for ?%s", async (search, title, action) => {
    serveGoals();
    serveTasks();
    renderTasks(search);

    expect(await screen.findByRole("heading", { name: title })).toBeInTheDocument();
    if (action) expect(screen.getAllByRole("button", { name: action }).length).toBeGreaterThan(0);
  });

  it("shows the linked goal's name on the row", async () => {
    const goal = makeGoal({ title: "Launch ClientPal" });
    serveGoals(goal);
    serveTasks(makeTask({ title: "Write the landing page", goal_id: goal.id }));
    renderTasks();

    const row = (await screen.findByText("Write the landing page")).closest("li")!;
    expect(await within(row).findByText("Launch ClientPal")).toBeInTheDocument();
  });
});

describe("done checkbox", () => {
  it("ticks at once, leaves the Open list after a pause, and Undo brings it back", async () => {
    serveGoals();
    const task = makeTask({ title: "Call the bank" });
    serveTasks(task);
    renderTasks();

    await userEvent.click(await screen.findByRole("checkbox", { name: "Mark “Call the bank” done" }));

    // Still there, ticked and struck through, until the pause is over.
    expect(screen.getByRole("checkbox", { name: "Mark “Call the bank” not done" })).toBeChecked();
    expect(screen.getByText("Call the bank")).toHaveClass("line-through");
    await waitFor(() => expect(sentBodies(`PATCH /tasks/${task.id}/status`)).toEqual([{ status: "done" }]));
    await waitFor(() => expect(screen.queryByText("Call the bank")).not.toBeInTheDocument(), { timeout: 3000 });

    await userEvent.click(await screen.findByRole("button", { name: "Undo" }));

    expect(await screen.findByText("Call the bank")).toBeInTheDocument();
    expect(sentBodies(`PATCH /tasks/${task.id}/status`)).toEqual([{ status: "done" }, { status: "open" }]);
  });

  it("waits to send while offline and stays in the list", async () => {
    serveGoals();
    const task = makeTask({ title: "Offline tick" });
    serveTasks(task);
    renderTasks();
    const checkbox = await screen.findByRole("checkbox", { name: "Mark “Offline tick” done" });

    act(() => onlineManager.setOnline(false));
    await userEvent.click(checkbox);

    const row = screen.getByText("Offline tick").closest("li")!;
    expect(await within(row).findByText("Waiting to send")).toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 1500));
    expect(screen.getByText("Offline tick")).toBeInTheDocument();
    expect(sentBodies(`PATCH /tasks/${task.id}/status`)).toEqual([]);

    act(() => onlineManager.setOnline(true));
    await waitFor(() => expect(sentBodies(`PATCH /tasks/${task.id}/status`)).toEqual([{ status: "done" }]));
  });
});

describe("creating a task", () => {
  it("sends null for 'Let MyPA suggest', fills the date from a chip, and links a goal", async () => {
    const goal = makeGoal({ title: "Launch ClientPal" });
    serveGoals(goal);
    serveTasks();
    renderTasks("task=new");

    const dialog = await panel();
    await userEvent.type(within(dialog).getByLabelText("Title"), "Buy the domain");
    await userEvent.click(within(dialog).getByRole("button", { name: "Tomorrow" }));
    expect(within(dialog).getByLabelText("Due date")).toHaveValue(addDays(today, 1));
    await pick("Goal", "Launch ClientPal");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create task" }));

    await waitFor(() =>
      expect(sentBodies("POST /tasks")).toEqual([
        {
          title: "Buy the domain",
          description: null,
          due_date: addDays(today, 1),
          urgency: null,
          effort_level: null,
          goal_id: goal.id,
        },
      ]),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(await screen.findByText("Task added")).toBeInTheDocument();
  });

  it("clears filters that would hide the new task", async () => {
    serveGoals();
    serveTasks();
    renderTasks("source=email&task=new");

    const dialog = await panel();
    await userEvent.type(within(dialog).getByLabelText("Title"), "Typed by hand");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create task" }));

    await waitFor(() => expect(navigation.replace).toHaveBeenLastCalledWith("/tasks"));
    expect(await screen.findByText("Typed by hand")).toBeInTheDocument();
  });
});

describe("AI guesses", () => {
  it("shows 'MyPA is suggesting…' for a new task the user left partly empty", async () => {
    serveGoals();
    serveTasks(
      makeTask({ title: "Fresh", created_at: new Date().toISOString() }),
      makeTask({
        title: "Hand-set",
        created_at: new Date().toISOString(),
        urgency_manually_set: true,
        effort_level: "passive",
        effort_level_manually_set: true,
      }),
    );
    renderTasks();

    const fresh = (await screen.findByText("Fresh")).closest("li")!;
    expect(within(fresh).getByText("MyPA is suggesting…")).toBeInTheDocument();
    const handSet = screen.getByText("Hand-set").closest("li")!;
    expect(within(handSet).queryByText("MyPA is suggesting…")).not.toBeInTheDocument();
  });
});

describe("editing a task", () => {
  it("sends only changed fields, and unlinking the goal sends null", async () => {
    const goal = makeGoal({ title: "Launch ClientPal" });
    serveGoals(goal);
    const task = makeTask({ title: "Write copy", goal_id: goal.id, urgency: "medium" });
    serveTasks(task);
    renderTasks(`task=${task.id}`);

    const dialog = await panel();
    await within(dialog).findByLabelText("Title");
    await pick("Goal", "No goal");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(sentBodies(`PATCH /tasks/${task.id}`)).toEqual([{ goal_id: null }]));
    // The backend now marks the goal link as set by hand.
    expect(await within(dialog).findByRole("button", { name: /You set this/ })).toBeInTheDocument();
  });

  it("offers Low / Medium / High only — urgency can't be emptied", async () => {
    serveGoals();
    const task = makeTask({ urgency: "medium" });
    serveTasks(task);
    renderTasks(`task=${task.id}`);

    await within(await panel()).findByLabelText("Title");
    await userEvent.click(screen.getByRole("combobox", { name: "Urgency" }));
    expect((await screen.findAllByRole("option")).map((o) => o.textContent)).toEqual(["Low", "Medium", "High"]);
  });

  it("shows pins only for fields set by hand", async () => {
    serveGoals();
    const task = makeTask({ title_manually_set: true, urgency_manually_set: true });
    serveTasks(task);
    renderTasks(`task=${task.id}`);

    const dialog = await panel();
    await within(dialog).findByLabelText("Title");
    expect(within(dialog).getAllByRole("button", { name: /You set this/ })).toHaveLength(2);
  });

  it("keeps a done goal as the current value", async () => {
    const goal = makeGoal({ title: "Launch v1", status: "done" });
    serveGoals(goal);
    const task = makeTask({ goal_id: goal.id });
    serveTasks(task);
    renderTasks(`task=${task.id}`);

    const dialog = await panel();
    await waitFor(() => expect(within(dialog).getByRole("combobox", { name: "Goal" })).toHaveTextContent("Launch v1 · Done"));
  });

  it("says when a task isn't available any more", async () => {
    serveGoals();
    serveTasks();
    renderTasks("task=00000000-0000-7000-9000-999999999999");

    expect(await within(await panel()).findByText("This task isn't available any more.")).toBeInTheDocument();
  });
});

describe("tasks and goals together", () => {
  it("drops the goal name from rows when that goal is deleted", async () => {
    const goal = makeGoal({ title: "Old plan" });
    serveGoals(goal);
    serveTasks(makeTask({ title: "Leftover", goal_id: goal.id }));
    function DeleteGoal() {
      const deleteGoal = useDeleteGoal();
      return <button onClick={() => deleteGoal.mutate({ id: goal.id })}>delete goal</button>;
    }
    renderTasks("", <DeleteGoal />);
    const row = (await screen.findByText("Leftover")).closest("li")!;
    await within(row).findByText("Old plan");

    await userEvent.click(screen.getByRole("button", { name: "delete goal" }));

    await waitFor(() => expect(screen.queryByText("Old plan")).not.toBeInTheDocument());
    expect(goalsDb.tasks[0].goal_id).toBeNull();
  });

  it("links a goal's tasks to Tasks", async () => {
    const goal = makeGoal();
    serveGoals(goal);
    const task = makeTask({ title: "Linked", goal_id: goal.id });
    serveTasks(task);
    function Harness() {
      useQueryClient();
      return <LinkedTasks goalId={goal.id} />;
    }
    renderWithProviders(<Harness />);

    expect(await screen.findByRole("link", { name: /Linked/ })).toHaveAttribute("href", `/tasks?task=${task.id}`);
  });
});
