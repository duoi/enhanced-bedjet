import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import TempArc from "./TempArc";

describe("TempArc", () => {
  it("renders without crashing with default fahrenheit values", () => {
    const { container } = render(
      <TempArc
        value={72}
        min={66}
        max={109}
        mode="standby"
        onChange={vi.fn()}
      />,
    );
    expect(container.querySelector(".temp-arc-wrap")).toBeInTheDocument();
  });

  it("renders without crashing with celsius values", () => {
    const { container } = render(
      <TempArc
        value={22}
        min={19}
        max={43}
        mode="cool"
        onChange={vi.fn()}
      />,
    );
    expect(container.querySelector(".temp-arc-wrap")).toBeInTheDocument();
  });

  it("renders without crashing when value equals min", () => {
    const { container } = render(
      <TempArc
        value={66}
        min={66}
        max={109}
        mode="heat"
        onChange={vi.fn()}
      />,
    );
    expect(container.querySelector(".temp-arc-wrap")).toBeInTheDocument();
  });

  it("renders without crashing when value equals max", () => {
    const { container } = render(
      <TempArc
        value={109}
        min={66}
        max={109}
        mode="turbo"
        onChange={vi.fn()}
      />,
    );
    expect(container.querySelector(".temp-arc-wrap")).toBeInTheDocument();
  });

  it("renders without crashing with no onChange (display-only)", () => {
    const { container } = render(
      <TempArc value={72} min={66} max={109} mode="cool" />,
    );
    expect(container.querySelector(".temp-arc-wrap")).toBeInTheDocument();
  });

  it("does not apply CSS transition on SVG path d attribute", () => {
    const { container } = render(
      <TempArc
        value={72}
        min={66}
        max={109}
        mode="cool"
        onChange={vi.fn()}
      />,
    );
    const paths = container.querySelectorAll(".temp-arc-wrap svg path");
    paths.forEach((path) => {
      expect(path.style.transition).not.toMatch(/\bd\b/);
    });
  });

  it("does not apply CSS transition on SVG circle cx/cy attributes", () => {
    const { container } = render(
      <TempArc
        value={72}
        min={66}
        max={109}
        mode="cool"
        onChange={vi.fn()}
      />,
    );
    const circles = container.querySelectorAll(".temp-arc-wrap svg circle");
    circles.forEach((circle) => {
      expect(circle.style.transition).not.toMatch(/\bcx\b/);
      expect(circle.style.transition).not.toMatch(/\bcy\b/);
    });
  });
});
