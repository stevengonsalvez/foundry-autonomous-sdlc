import type { ParcelEvent, ParcelStatus } from "@parcel/core";
import { CheckIcon, StatusIcon } from "./Icons";

export interface ProgressBarProps {
  status: ParcelStatus;
  events?: ParcelEvent[];
}

interface JourneyStage {
  id: string;
  label: string;
}

const STAGES: readonly JourneyStage[] = [
  { id: "label_created", label: "Label created" },
  { id: "in_transit", label: "In transit" },
  { id: "out_for_delivery", label: "Out for delivery" },
  { id: "delivered", label: "Delivered" },
] as const;

function getActiveStageIndex(status: ParcelStatus, events?: ParcelEvent[]): number {
  if (status === "label_created") return 0;
  if (status === "in_transit") return 1;
  if (status === "out_for_delivery") return 2;
  if (status === "delivered") return 3;
  if (status === "exception") {
    if (events && events.length > 0) {
      for (const event of events) {
        const desc = event.description.toLowerCase();
        if (desc.includes("out for delivery") || desc.includes("delivery attempt")) {
          return 2;
        }
      }
      for (const event of events) {
        const desc = event.description.toLowerCase();
        if (
          desc.includes("transit") ||
          desc.includes("departed") ||
          desc.includes("arrived") ||
          desc.includes("picked up") ||
          desc.includes("customs") ||
          desc.includes("hub") ||
          desc.includes("facility") ||
          desc.includes("depot")
        ) {
          return 1;
        }
      }
      if (events.some((e) => e.description.toLowerCase().includes("label"))) {
        return 0;
      }
    }
    return 1;
  }
  return 0;
}

export function ProgressBar({ status, events }: ProgressBarProps) {
  const activeIndex = getActiveStageIndex(status, events);
  const isException = status === "exception";
  const progressPercent = Math.round(((activeIndex + 1) / STAGES.length) * 100);

  return (
    <div
      className="progress-stepper"
      data-testid="journey-progress-stepper"
      role="progressbar"
      aria-label="Parcel journey progress"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={progressPercent}
      aria-valuetext={STAGES[activeIndex]?.label}
    >
      <div className="progress-stepper__track" aria-hidden="true">
        <div
          className={`progress-stepper__bar${isException ? " progress-stepper__bar--exception" : ""}`}
          style={{ width: `${(activeIndex / (STAGES.length - 1)) * 100}%` }}
        />
      </div>
      <div className="progress-stepper__stages">
        {STAGES.map((stage, index) => {
          const isCurrent = status !== "delivered" && index === activeIndex;
          const isCompleted = index < activeIndex || (index === activeIndex && status === "delivered");

          let stepState: "completed" | "active" | "exception" | "upcoming";
          if (isCurrent && isException) {
            stepState = "exception";
          } else if (isCurrent) {
            stepState = "active";
          } else if (isCompleted) {
            stepState = "completed";
          } else {
            stepState = "upcoming";
          }

          return (
            <div
              key={stage.id}
              className={`progress-stepper__step progress-stepper__step--${stepState}${
                isCurrent ? " is-active" : ""
              }${isCompleted ? " is-completed" : ""}${
                isCurrent && isException ? " is-exception" : ""
              }`}
              data-step-state={stepState}
              data-stage={stage.id}
              data-active={isCurrent ? "true" : undefined}
              data-completed={isCompleted ? "true" : undefined}
              aria-current={isCurrent ? "step" : undefined}
            >
              <div className="progress-stepper__node" aria-hidden="true">
                {isCompleted ? (
                  <span className="progress-stepper__icon" data-testid="step-checkmark">
                    <CheckIcon size={14} />
                  </span>
                ) : isCurrent && isException ? (
                  <span className="progress-stepper__icon" data-testid="step-exception">
                    <StatusIcon status="exception" />
                  </span>
                ) : (
                  <span className="progress-stepper__number">{index + 1}</span>
                )}
              </div>
              <span className="progress-stepper__label">{stage.label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default ProgressBar;
