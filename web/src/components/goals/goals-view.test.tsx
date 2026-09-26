import { onlineManager } from "@tanstack/react-query";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";

import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { queryKeys } from "@/lib/api/query-config";
import { goalsDb, makeGoal, makeTask, sentBodies, serveGoals } from "@/test/goals-server";
import { navigation } from "@/test/navigation-mock";
import { renderWithProviders } from "@/test/render";
import { API, server } from "@/test/server";
import { GoalsView } from "./goals-view";

function renderGoals(search = "") {
  navigation.pathname = "/goals";
  navigation.search = search;
  return renderWithProviders(
    <TooltipProvider>
      <GoalsView />
      <Toaster />
    </TooltipProvider>,
  );
}

const goalList = () => screen.findByRole("list", { name: "Goals" });
const panel = () => screen.findByRole("dialog");

afterEach(() => {
  act(() => onlineManager.setOnline(true));
});

describe("goal list", () => {
  it("asks for active goals, 50 at a time, and shows a skeleton first", async () => {
    serveGoals(makeGoal({ title: "Launch ClientPal" }));
    renderGoals();

    expect(screen.getByLabelText("Loading goals")).toBeInTheDocument();
    expect(await within(await goalList()).findByText("Launch ClientPal")).toBeInTheDocument();
    const query = new URLSearchParams(sentBodies("GET /goals")[0] as string);
    expect(query.getAll("status")).toEqual(["open", "paused"]);
    expect(query.get("items_per_page")).toBe("50");
  });

  it("switches views through the filter and the URL", async () => {
    serveGoals(makeGoal({ title: "Still going" }), makeGoal({ title: "Shipped it", status: "done" }));
    renderGoals();
    await within(await goalList()).findByText("Still going");

    await userEvent.click(screen.getByRole("radio", { name: "Done" }));

    expect(navigation.replace).toHaveBeenLastCalledWith("/goals?status=done");
    expect(await screen.findByText("Shipped it")).toBeInTheDocument();
    expect(screen.queryByText("Still going")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("radio", { name: "All" }));
    expect(await screen.findByText("Still going")).toBeInTheDocument();
    expect(new URLSearchParams(sentBodies("GET /goals").at(-1) as string).getAll("status")).toEqual([]);
  });

  it("loads the next page on request", async () => {
    serveGoals(...Array.from({ length: 51 }, (_, i) => makeGoal({ title: `Goal number ${i + 1}` })));
    renderGoals();
    const list = await goalList();
    expect(within(list).getAllByRole("listitem")).toHaveLength(50);

    await userEvent.click(screen.getByRole("button", { name: "Load more" }));

    await waitFor(() => expect(within(list).getAllByRole("listitem")).toHaveLength(51));
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  }, 20_000); // 51 rows with their menus are slow to render in jsdom

  it.each([
    ["", "What are you working toward?", true],
    ["status=done", "Nothing finished yet.", false],
    ["status=dropped", "Nothing dropped.", false],
  ])("shows the empty state for ?%s", async (search, title, hasAction) => {
    serveGoals();
    renderGoals(search);

    expect(await screen.findByRole("heading", { name: title })).toBeInTheDocument();
    // The header always has "New goal"; only Active/All add one to the empty state.
    expect(screen.getAllByRole("button", { name: "New goal" })).toHaveLength(hasAction ? 2 : 1);
  });

  it("marks a paused goal", async () => {
    serveGoals(makeGoal({ status: "paused" }));
    renderGoals();

    expect(await screen.findByRole("button", { name: "Status: Paused. Change status" })).toBeInTheDocument();
  });
});

describe("creating a goal", () => {
  it("sends empty horizon and date as null, shows the row at once, then the server's", async () => {
    serveGoals(makeGoal({ title: "Older goal" }));
    let release!: () => void;
    const held = new Promise<void>((resolve) => (release = resolve));
    server.use(
      http.post(`${API}/goals`, async ({ request }) => {
        const body = await request.json();
        goalsDb.bodies.set("POST /goals", [body]);
        await held;
        const goal = makeGoal({ ...(body as object), created_at: new Date().toISOString() });
        goalsDb.goals.unshift(goal);
        return HttpResponse.json(goal, { status: 201 });
      }),
    );
    renderGoals();
    await goalList();

    await userEvent.click(screen.getByRole("button", { name: "New goal" }));
    expect(navigation.push).toHaveBeenLastCalledWith("/goals?goal=new");
    const dialog = await panel();
    await userEvent.type(within(dialog).getByLabelText("Title"), "Run a marathon");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create goal" }));

    // Optimistic row while the server hasn't answered (the list is aria-hidden behind the sheet).
    const list = await screen.findByRole("list", { name: "Goals", hidden: true });
    expect(await within(list).findByText("Run a marathon")).toBeInTheDocument();
    expect(within(list).getAllByRole("listitem", { hidden: true })[0]).toHaveClass("opacity-70");
    expect(sentBodies("POST /goals")).toEqual([
      { title: "Run a marathon", description: null, horizon: null, target_date: null },
    ]);

    release();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(within(list).getAllByRole("listitem")[0]).not.toHaveClass("opacity-70");
    expect(await screen.findByText("Goal added")).toBeInTheDocument();
  });

  it("switches to Active when the goal was added from the Done view", async () => {
    serveGoals();
    renderGoals("status=done");
    await screen.findByRole("heading", { name: "Nothing finished yet." });

    await userEvent.click(screen.getByRole("button", { name: "New goal" }));
    const dialog = await panel();
    await userEvent.type(within(dialog).getByLabelText("Title"), "Learn Portuguese");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create goal" }));

    await waitFor(() => expect(navigation.replace).toHaveBeenLastCalledWith("/goals"));
    expect(await within(await goalList()).findByText("Learn Portuguese")).toBeInTheDocument();
  });

  it("keeps the form filled and shows the error when the server refuses", async () => {
    serveGoals();
    server.use(http.post(`${API}/goals`, () => HttpResponse.json({ detail: "Title is too long" }, { status: 422 })));
    renderGoals("goal=new");

    const dialog = await panel();
    await userEvent.type(within(dialog).getByLabelText("Title"), "Something");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create goal" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Title is too long");
    expect(within(dialog).getByLabelText("Title")).toHaveValue("Something");
  });

  it("waits to send while offline, then sends once back online", async () => {
    serveGoals();
    renderGoals("goal=new");
    const dialog = await panel();
    await userEvent.type(within(dialog).getByLabelText("Title"), "Offline goal");

    act(() => onlineManager.setOnline(false));
    await userEvent.click(within(dialog).getByRole("button", { name: "Create goal" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const row = (await within(await goalList()).findByText("Offline goal")).closest("li")!;
    expect(within(row).getByText("Waiting to send")).toBeInTheDocument();
    expect(sentBodies("POST /goals")).toEqual([]);

    act(() => onlineManager.setOnline(true));

    await waitFor(() => expect(sentBodies("POST /goals")).toHaveLength(1));
    await waitFor(() => expect(screen.queryByText("Waiting to send")).not.toBeInTheDocument());
  });
});

describe("AI horizon guess", () => {
  it("shows 'MyPA is suggesting…' for a new goal and re-checks until the horizon arrives", async () => {
    const goal = makeGoal({ title: "Fresh goal", horizon: null, created_at: new Date().toISOString() });
    serveGoals(goal);
    renderGoals();

    expect(await within(await goalList()).findByText("MyPA is suggesting…")).toBeInTheDocument();
    goal.horizon = "long_term";

    expect(await screen.findByText("Long-term", {}, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.queryByText("MyPA is suggesting…")).not.toBeInTheDocument();
  });

  it("shows 'Not set' for an older goal with no horizon", async () => {
    serveGoals(makeGoal({ horizon: null }));
    renderGoals();

    expect(await within(await goalList()).findByText("Not set")).toBeInTheDocument();
  });
});

describe("editing a goal", () => {
  it("opens from the URL and sends only the fields that changed", async () => {
    const goal = makeGoal({ title: "Launch ClientPal", description: "Landing page first" });
    serveGoals(goal);
    renderGoals(`goal=${goal.id}`);

    const dialog = await panel();
    expect(await within(dialog).findByRole("heading", { name: "Launch ClientPal" })).toBeInTheDocument();
    const description = await within(dialog).findByLabelText("Description");
    await userEvent.clear(description);
    await userEvent.type(description, "Pricing page first");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(sentBodies(`PATCH /goals/${goal.id}`)).toEqual([{ description: "Pricing page first" }]));
    // The backend now marks the description as set by hand.
    expect(await within(dialog).findByRole("button", { name: /You set this/ })).toBeInTheDocument();
  });

  it("sends null when the target date is cleared", async () => {
    const goal = makeGoal({ target_date: "2027-03-01" });
    serveGoals(goal);
    renderGoals(`goal=${goal.id}`);

    const dialog = await panel();
    // user-event can't select text in a date input; a change event is what the browser sends.
    fireEvent.change(await within(dialog).findByLabelText("Target date"), { target: { value: "" } });
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(sentBodies(`PATCH /goals/${goal.id}`)).toEqual([{ target_date: null }]));
  });

  it("asks before throwing away unsaved changes", async () => {
    const goal = makeGoal();
    serveGoals(goal);
    renderGoals(`goal=${goal.id}`);

    const dialog = await panel();
    await userEvent.type(await within(dialog).findByLabelText("Title"), " again");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    const confirm = await screen.findByRole("alertdialog", { name: "Discard changes?" });
    await userEvent.click(within(confirm).getByRole("button", { name: "Keep editing" }));
    expect(within(dialog).getByLabelText("Title")).toHaveValue(`${goal.title} again`);
    expect(navigation.replace).not.toHaveBeenCalled();
  });

  it("shows a server error inline and keeps the form", async () => {
    const goal = makeGoal();
    serveGoals(goal);
    server.use(
      http.patch(`${API}/goals/:id`, () =>
        HttpResponse.json({ detail: [{ loc: ["body", "title"], msg: "String too long", type: "x" }] }, { status: 422 }),
      ),
    );
    renderGoals(`goal=${goal.id}`);

    const dialog = await panel();
    await userEvent.type(await within(dialog).findByLabelText("Title"), " edited");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent("String too long");
    expect(within(dialog).getByLabelText("Title")).toHaveValue(`${goal.title} edited`);
  });

  it("shows pins only for fields set by hand", async () => {
    const goal = makeGoal({ title_manually_set: true, description_manually_set: false });
    serveGoals(goal);
    renderGoals(`goal=${goal.id}`);

    const dialog = await panel();
    await within(dialog).findByLabelText("Title");
    expect(within(dialog).getAllByRole("button", { name: /You set this/ })).toHaveLength(1);
  });

  it("says when a goal isn't available any more", async () => {
    serveGoals();
    renderGoals("goal=00000000-0000-7000-8000-999999999999");

    expect(await within(await panel()).findByText("This goal isn't available any more.")).toBeInTheDocument();
  });

  it("closes when the URL loses ?goal (the Back button)", async () => {
    const goal = makeGoal();
    serveGoals(goal);
    renderGoals(`goal=${goal.id}`);
    await panel();

    act(() => navigation.replace("/goals"));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("returns focus to the row after the panel closes", async () => {
    serveGoals(makeGoal({ title: "Launch ClientPal" }));
    renderGoals();
    const row = await within(await goalList()).findByRole("button", { name: "Launch ClientPal" });

    await userEvent.click(row);
    await within(await panel()).findByLabelText("Title");
    await userEvent.keyboard("{Escape}");

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(row).toHaveFocus());
  });

  it("lists the linked tasks with a count", async () => {
    const goal = makeGoal();
    serveGoals(goal);
    goalsDb.tasks = [
      makeTask({ title: "Write the landing page", goal_id: goal.id }),
      makeTask({ title: "Buy the domain", goal_id: goal.id, status: "done" }),
    ];
    renderGoals(`goal=${goal.id}`);

    const dialog = await panel();
    expect(await within(dialog).findByRole("heading", { name: "2 tasks · 1 done" })).toBeInTheDocument();
    expect(within(dialog).getByText("Write the landing page")).toBeInTheDocument();
  });

  it("says when no tasks are linked", async () => {
    const goal = makeGoal();
    serveGoals(goal);
    renderGoals(`goal=${goal.id}`);

    expect(await within(await panel()).findByText("No tasks linked yet.")).toBeInTheDocument();
  });
});

describe("status", () => {
  it("changes from the row menu, leaves the Active list, and can be undone", async () => {
    const goal = makeGoal({ title: "Launch ClientPal" });
    serveGoals(goal);
    renderGoals();
    const list = await goalList();
    await within(list).findByText("Launch ClientPal");

    await userEvent.click(within(list).getByRole("button", { name: "Status: Open. Change status" }));
    await userEvent.click(await screen.findByRole("menuitemradio", { name: "Done" }));

    await waitFor(() => expect(screen.queryByText("Launch ClientPal")).not.toBeInTheDocument());
    expect(sentBodies(`PATCH /goals/${goal.id}/status`)).toEqual([{ status: "done" }]);

    await userEvent.click(await screen.findByRole("button", { name: "Undo" }));

    expect(await screen.findByText("Launch ClientPal")).toBeInTheDocument();
    expect(sentBodies(`PATCH /goals/${goal.id}/status`)).toEqual([{ status: "done" }, { status: "open" }]);
  });
});

describe("deleting a goal", () => {
  it("asks first, then removes it and refreshes its linked tasks", async () => {
    const goal = makeGoal({ title: "Old plan" });
    serveGoals(goal);
    const { queryClient } = renderGoals(`goal=${goal.id}`);
    const dialog = await panel();
    await within(dialog).findByText("No tasks linked yet.");

    await userEvent.click(within(dialog).getByRole("button", { name: "Delete goal" }));
    const confirm = await screen.findByRole("alertdialog", { name: "Delete this goal?" });
    expect(sentBodies(`DELETE /goals/${goal.id}`)).toEqual([]);
    await userEvent.click(within(confirm).getByRole("button", { name: "Delete goal" }));

    await waitFor(() => expect(sentBodies(`DELETE /goals/${goal.id}`)).toHaveLength(1));
    await waitFor(() => expect(screen.queryByText("Old plan")).not.toBeInTheDocument());
    expect(queryClient.getQueryState(queryKeys.tasks.byGoal(goal.id))?.isInvalidated).toBe(true);
  });
});
