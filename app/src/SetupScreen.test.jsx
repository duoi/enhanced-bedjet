import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import SetupScreen from "./SetupScreen";

let mockTestHubConnection;

vi.mock("./api", () => ({
  testHubConnection: (...args) => mockTestHubConnection(...args),
  DEFAULT_HUB_ADDRESS: "10.0.0.175:8265",
}));

beforeEach(() => {
  vi.clearAllMocks();
  mockTestHubConnection = vi.fn(() => Promise.reject(new Error("no hub")));
});

describe("SetupScreen", () => {
  it("renders without crashing", () => {
    const { container } = render(
      <SetupScreen onConnect={vi.fn()} onSkip={() => {}} />,
    );
    expect(container).toBeInTheDocument();
  });

  it("probes the proxy on mount", async () => {
    render(<SetupScreen onConnect={vi.fn()} onSkip={() => {}} />);

    await waitFor(() => {
      expect(mockTestHubConnection).toHaveBeenCalledWith("");
    });
  });

  it("auto-connects when proxy probe succeeds", async () => {
    mockTestHubConnection.mockResolvedValueOnce({ connected: true });
    const onConnect = vi.fn();

    render(<SetupScreen onConnect={onConnect} onSkip={() => {}} />);

    await waitFor(() => {
      expect(onConnect).toHaveBeenCalledWith("");
    });
  });

  it("shows manual input when proxy probe fails", async () => {
    render(<SetupScreen onConnect={vi.fn()} onSkip={() => {}} />);

    await waitFor(() => {
      expect(
        screen.getByPlaceholderText("10.0.0.175:8265"),
      ).toBeInTheDocument();
    });
  });

  it("connects with manual address after probe fails", async () => {
    mockTestHubConnection
      .mockRejectedValueOnce(new Error("no proxy"))
      .mockResolvedValueOnce({ connected: true });
    const onConnect = vi.fn();

    render(<SetupScreen onConnect={onConnect} onSkip={() => {}} />);

    await waitFor(() => {
      expect(
        screen.getByPlaceholderText("10.0.0.175:8265"),
      ).toBeInTheDocument();
    });

    fireEvent.change(screen.getByPlaceholderText("10.0.0.175:8265"), {
      target: { value: "10.0.0.5:8265" },
    });
    fireEvent.click(screen.getByText("Connect"));

    await waitFor(() => {
      expect(onConnect).toHaveBeenCalledWith("10.0.0.5:8265");
    });
  });
});
