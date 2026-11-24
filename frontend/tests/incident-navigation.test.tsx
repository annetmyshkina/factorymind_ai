import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../src/App";
import { loadCurrentUser, loadDashboard, loadIncidentWorkspace, login, updateIncident } from "../src/api";
import { demoData } from "../src/demo";
import type { CurrentUser, DashboardData, Incident, IncidentWorkspace } from "../src/types";

vi.mock("../src/api", async (importOriginal) => ({
  ...await importOriginal<typeof import("../src/api")>(),
  loadCurrentUser: vi.fn(),
  login: vi.fn(),
  loadDashboard: vi.fn(),
  loadIncidentWorkspace: vi.fn(),
  updateIncident: vi.fn(),
}));

let data: DashboardData;

const currentUser: CurrentUser = {
  id: 1,
  username: "test-admin",
  full_name: "Test Administrator",
  role: "admin",
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
};

beforeEach(() => {
  window.history.replaceState(null, "", "/");
  localStorage.clear();
  sessionStorage.clear();
  sessionStorage.setItem("factorymind-access-token", "test-token");
  vi.clearAllMocks();
  data = structuredClone(demoData);
  vi.mocked(loadCurrentUser).mockResolvedValue(currentUser);
  vi.mocked(login).mockResolvedValue(currentUser);
  vi.mocked(loadDashboard).mockImplementation(async () => ({ data: structuredClone(data), mode: "live" }));
  vi.mocked(loadIncidentWorkspace).mockImplementation(async (id): Promise<IncidentWorkspace> => ({
    detail: { ...data.incidents.find((item) => item.id === id)!, deviation_ids: [], events: [] },
    deviations: [], analyses: [], resolution: null,
  }));
  vi.mocked(updateIncident).mockImplementation(async (id, payload): Promise<Incident> => {
    const incident = data.incidents.find((item) => item.id === id)!;
    Object.assign(incident, payload);
    return { ...incident };
  });
});

afterEach(cleanup);

async function openIncidentList() {
  await screen.findByText("Данные в реальном времени");
  fireEvent.click(within(screen.getByRole("navigation", { name: "Основная навигация" })).getByRole("button", { name: /Инциденты/ }));
  fireEvent.click(screen.getByRole("button", { name: "Все" }));
  fireEvent.click(screen.getByRole("button", { name: /Высокая температура нагнетания/ }));
  return screen.findByRole("combobox", { name: "Критичность" });
}

function expectIncidentList() {
  expect(screen.getByRole("heading", { name: "Инциденты", level: 1 })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Все" }).className).toContain("active");
  expect(screen.getByRole("dialog")).toBeTruthy();
}

describe("Навигация при сохранении инцидента", () => {
  it("остаётся в списке и открытой карточке после применения критичности", async () => {
    render(<App />);
    const severity = await openIncidentList();
    fireEvent.change(severity, { target: { value: "high" } });
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Применить" }));
    await screen.findByText("Критичность обновлена.");
    expect(updateIncident).toHaveBeenCalledWith(148, { severity: "high" });
    expectIncidentList();
    fireEvent.click(screen.getByRole("button", { name: "Закрыть карточку" }));
    expect(screen.getByRole("heading", { name: "Инциденты", level: 1 })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Все" }).className).toContain("active");
  });

  it("сохраняет список, фильтр и карточку после перезапуска приложения", async () => {
    const app = render(<App />);
    const severity = await openIncidentList();
    fireEvent.change(severity, { target: { value: "high" } });
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Применить" }));
    await screen.findByText("Критичность обновлена.");
    app.unmount();
    render(<App />);
    await screen.findByText("Данные в реальном времени");
    await waitFor(expectIncidentList);
    expect((await screen.findByRole("combobox", { name: "Критичность" }) as HTMLSelectElement).value).toBe("high");
  });

  it("оставляет список и карточку на месте при ошибке сохранения", async () => {
    vi.mocked(updateIncident).mockRejectedValueOnce(new Error("Не удалось сохранить"));
    render(<App />);
    const severity = await openIncidentList();
    fireEvent.change(severity, { target: { value: "high" } });
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Применить" }));
    await screen.findByText("Не удалось сохранить");
    expectIncidentList();
    expect(screen.queryByText("Критичность обновлена.")).toBeNull();
  });

  it("открывает список и карточку по прямой ссылке без серверного маршрута", async () => {
    window.history.replaceState(null, "", "/ui/#incidents?filter=all&incident=148");
    render(<App />);
    await screen.findByRole("combobox", { name: "Критичность" });
    expectIncidentList();
  });
});

describe("Аутентификация оператора", () => {
  it("показывает вход без сохранённой сессии", async () => {
    sessionStorage.clear();
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Вход в систему" })).toBeTruthy();
    expect(loadDashboard).not.toHaveBeenCalled();
  });

  it("после успешного входа загружает рабочий экран", async () => {
    sessionStorage.clear();
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "Войти" }));

    await screen.findByText("Данные в реальном времени");
    expect(login).toHaveBeenCalledWith("admin", "admin");
    expect(loadDashboard).toHaveBeenCalled();
  });
});
