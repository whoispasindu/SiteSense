import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CurveTooltip } from "./SCurve";

type Props = Parameters<typeof CurveTooltip>[0];

function tooltip(props: Partial<Props>) {
  return render(<CurveTooltip {...({ active: true, payload: [], label: "2026-10-09", ...props } as Props)} />);
}

describe("S-curve tooltip", () => {
  it("shows planned and actual for the hovered date", () => {
    tooltip({ payload: [{ dataKey: "planned", value: 27.4 }, { dataKey: "actual", value: 23 }] as unknown as Props["payload"] });

    expect(screen.getByText("09 Oct 2026")).toBeInTheDocument();
    expect(screen.getByText("Planned 27.4%")).toBeInTheDocument();
    expect(screen.getByText("Actual 23.0%")).toBeInTheDocument();
  });

  it("shows a dash where there is no actual yet, and nothing when inactive", () => {
    tooltip({ payload: [{ dataKey: "planned", value: 50 }] as unknown as Props["payload"] });
    expect(screen.getByText("Actual —")).toBeInTheDocument();

    const { container } = render(<CurveTooltip {...({ active: false, payload: [], label: 0 } as unknown as Props)} />);
    expect(container).toBeEmptyDOMElement();
  });
});
