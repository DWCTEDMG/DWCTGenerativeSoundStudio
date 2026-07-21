import React from "react";
import type { QueueJobAction } from "./jobActions";
import {
  canCancelJob,
  canPauseJob,
  canResumeJob,
  canRetryJob,
  canUseCheckpointRecovery,
  type StudioJob,
} from "./jobStatus";

type JobActionButtonsProps = {
  job: StudioJob;
  onAction: (action: QueueJobAction) => void | Promise<unknown>;
  onResumeFromCheckpoint?: () => void | Promise<unknown>;
  onRestartClean?: () => void | Promise<unknown>;
};

export function JobActionButtons({
  job,
  onAction,
  onResumeFromCheckpoint,
  onRestartClean,
}: JobActionButtonsProps) {
  const checkpointRecoveryAvailable = canUseCheckpointRecovery(job.status);

  return (
    <>
      {canPauseJob(job.status) ? (
        <button
          className="secondary"
          title="Pausing holds this queued job and never interrupts an active render."
          onClick={() => void onAction("pause")}
        >
          Pause
        </button>
      ) : null}
      {canResumeJob(job.status) ? (
        <button className="secondary" onClick={() => void onAction("resume")}>
          Resume queued job
        </button>
      ) : null}
      {onResumeFromCheckpoint && checkpointRecoveryAvailable ? (
        <button className="secondary" onClick={() => void onResumeFromCheckpoint()}>
          Resume from checkpoint
        </button>
      ) : null}
      {onRestartClean && checkpointRecoveryAvailable ? (
        <button className="secondary" onClick={() => void onRestartClean()}>
          Restart clean
        </button>
      ) : null}
      {canRetryJob(job.status) ? (
        <button className="secondary" onClick={() => void onAction("retry")}>
          Retry
        </button>
      ) : null}
      {canCancelJob(job.status) ? (
        <button className="secondary" onClick={() => void onAction("cancel")}>
          Cancel
        </button>
      ) : null}
    </>
  );
}
