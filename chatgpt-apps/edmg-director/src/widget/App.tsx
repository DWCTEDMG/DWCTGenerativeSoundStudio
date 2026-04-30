import { useEffect, useState } from "react";

type PlanScene = {
  index: number;
  name: string;
  startS: number;
  endS: number;
  promptSnippet?: string;
  transition?: string;
};

type PlanVariant = {
  index: number;
  name: string;
  sceneCount: number;
  durationS: number;
  scenes?: PlanScene[];
};

type PlanPreviewOutput = {
  kind: "planPreview";
  projectId: string;
  projectName?: string;
  planMode?: string;
  generatedAt?: string;
  variants?: PlanVariant[];
};

type ActionResultOutput = {
  kind: "actionResult";
  title?: string;
  message?: string;
  projectId?: string;
  projectName?: string;
  variantIndex?: number;
  overwrite?: boolean;
};

type GenericOutput = Record<string, unknown> | null;

type HostApi = {
  toolOutput?: GenericOutput;
  theme?: string;
  callTool?: (name: string, args: Record<string, unknown>) => Promise<any>;
  sendFollowUpMessage?: (message: {
    role: string;
    content: Array<{ type: string; text: string }>;
  }) => Promise<unknown>;
  requestDisplayMode?: (args: { mode: string }) => Promise<unknown>;
};

declare global {
  interface Window {
    openai?: HostApi;
  }
}

function host(): HostApi {
  return window.openai ?? {};
}

function readToolOutput(event?: Event): GenericOutput {
  const detail = (event as CustomEvent<{ globals?: { toolOutput?: GenericOutput } }> | undefined)?.detail;
  return detail?.globals?.toolOutput ?? host().toolOutput ?? null;
}

function applyTheme() {
  document.documentElement.dataset.theme = host().theme ?? "light";
}

function formatSeconds(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "0:00";
  const mins = Math.floor(value / 60);
  const secs = Math.round(value % 60)
    .toString()
    .padStart(2, "0");
  return `${mins}:${secs}`;
}

function isPlanPreview(output: GenericOutput): output is PlanPreviewOutput {
  return Boolean(output && output.kind === "planPreview");
}

function isActionResult(output: GenericOutput): output is ActionResultOutput {
  return Boolean(output && output.kind === "actionResult");
}

function StatusBanner(props: { busy: string; error: string }) {
  if (!props.busy && !props.error) return null;
  return <div className={`status${props.error ? " error" : ""}`}>{props.error || props.busy}</div>;
}

function Hero(props: { title: string; summary: string; children?: React.ReactNode }) {
  return (
    <section className="hero">
      <div className="eyebrow">EDMG Director</div>
      <h1 className="title">{props.title}</h1>
      <p className="summary">{props.summary}</p>
      {props.children}
    </section>
  );
}

function PlanPreviewView(props: {
  output: PlanPreviewOutput;
  onApply: (projectId: string, variantIndex: number, overwrite: boolean) => Promise<void>;
  onAsk: (projectId: string, variantIndex: number) => Promise<void>;
  onExpand: () => Promise<void>;
}) {
  const variants = props.output.variants ?? [];
  return (
    <>
      <Hero
        title={props.output.projectName || props.output.projectId || "Project review"}
        summary="Review the generated EDMG storyboard variants below, then apply the best one to the timeline."
      >
        <div className="metaRow">
          <span className="badge badgeAccent">Plan mode: {props.output.planMode || "auto"}</span>
          <span className="badge">Generated: {props.output.generatedAt || ""}</span>
          <span className="badge badgeGood">Variants: {variants.length}</span>
        </div>
        <div className="buttonRow">
          <button className="button" onClick={() => void props.onExpand()}>
            Open larger
          </button>
        </div>
      </Hero>
      <div className="grid">
        {variants.length ? (
          variants.map((variant) => (
            <section className="variant" key={`${props.output.projectId}-${variant.index}`}>
              <div className="variantHead">
                <div>
                  <h3 className="variantTitle">{variant.name}</h3>
                  <div className="variantSub">
                    {variant.sceneCount} scenes · approx {formatSeconds(variant.durationS)}
                  </div>
                </div>
                <div className="variantActions">
                  <button
                    className="button buttonPrimary"
                    onClick={() => void props.onApply(props.output.projectId, variant.index, false)}
                  >
                    Apply to timeline
                  </button>
                  <button className="button" onClick={() => void props.onApply(props.output.projectId, variant.index, true)}>
                    Apply with overwrite
                  </button>
                  <button className="button buttonGhost" onClick={() => void props.onAsk(props.output.projectId, variant.index)}>
                    Ask ChatGPT for notes
                  </button>
                </div>
              </div>
              <div className="sceneList">
                {(variant.scenes ?? []).map((scene) => (
                  <article className="scene" key={`${variant.index}-${scene.index}`}>
                    <div className="sceneHead">
                      <div>
                        <h4 className="sceneName">{scene.name}</h4>
                        <div className="sceneMeta">
                          Scene {scene.index + 1} · {formatSeconds(scene.startS)} → {formatSeconds(scene.endS)}
                        </div>
                      </div>
                    </div>
                    <p className="scenePrompt">{scene.promptSnippet || "No prompt snippet available."}</p>
                    {scene.transition ? (
                      <div className="sceneTransition">
                        <strong>Transition:</strong> {scene.transition}
                      </div>
                    ) : null}
                  </article>
                ))}
              </div>
            </section>
          ))
        ) : (
          <div className="status">No variants were returned by the EDMG backend.</div>
        )}
      </div>
      <div className="finePrint">
        This widget is intentionally thin. The EDMG backend remains the source of truth for analysis, plan storage, and timeline state.
      </div>
    </>
  );
}

function ActionResultView(props: {
  output: ActionResultOutput;
  onAskNext: (projectId: string, variantIndex: number) => Promise<void>;
  onExpand: () => Promise<void>;
}) {
  const projectId = props.output.projectId || "";
  const variantIndex = props.output.variantIndex ?? 0;
  return (
    <Hero title={props.output.title || "Action complete"} summary={props.output.message || "The requested EDMG action completed."}>
      <div className="metaRow">
        <span className="badge badgeGood">Project: {props.output.projectName || projectId}</span>
        <span className="badge">Variant: {variantIndex + 1}</span>
        {props.output.overwrite ? <span className="badge badgeAccent">Overwrite applied</span> : null}
      </div>
      <div className="buttonRow">
        <button className="button buttonPrimary" onClick={() => void props.onAskNext(projectId, variantIndex)}>
          Ask ChatGPT for next EDMG step
        </button>
        <button className="button" onClick={() => void props.onExpand()}>
          Open larger
        </button>
      </div>
    </Hero>
  );
}

function FallbackView(props: { output: GenericOutput }) {
  return (
    <>
      <Hero
        title="Tool output"
        summary="This view only has a custom layout for plan previews and apply confirmations."
      />
      <pre className="status">{JSON.stringify(props.output ?? {}, null, 2)}</pre>
    </>
  );
}

export default function App() {
  const [output, setOutput] = useState<GenericOutput>(() => readToolOutput());
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    applyTheme();
    const onGlobals = (event: Event) => {
      applyTheme();
      setOutput(readToolOutput(event));
    };

    window.addEventListener("openai:set_globals", onGlobals as EventListener, { passive: true });
    return () => {
      window.removeEventListener("openai:set_globals", onGlobals as EventListener);
    };
  }, []);

  useEffect(() => {
    applyTheme();
  }, [output]);

  const applyPlanVariant = async (projectId: string, variantIndex: number, overwrite: boolean) => {
    setError("");
    setBusy("Applying the selected EDMG variant to the timeline…");
    try {
      if (!host().callTool) {
        throw new Error("This host does not expose window.openai.callTool.");
      }
      const result = await host().callTool("apply_plan_variant", {
        projectId,
        variantIndex,
        overwrite,
      });
      if (result?.isError) {
        throw new Error(
          Array.isArray(result.content)
            ? result.content
                .map((item: { text?: string }) => item?.text || "")
                .filter(Boolean)
                .join(" ")
            : "The EDMG apply tool reported an error."
        );
      }
      setBusy("");
      setError("");
      setOutput(
        result?.structuredContent ?? {
          kind: "actionResult",
          title: "Timeline updated",
          message: "The EDMG timeline was updated.",
          projectId,
          variantIndex,
          overwrite,
        }
      );
    } catch (caught) {
      setBusy("");
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  };

  const askForNotes = async (projectId: string, variantIndex: number) => {
    if (!host().sendFollowUpMessage) return;
    await host().sendFollowUpMessage({
      role: "user",
      content: [
        {
          type: "text",
          text: `Summarize the EDMG storyboard differences for project ${projectId} and focus on variant ${variantIndex + 1}.`,
        },
      ],
    });
  };

  const askForNextStep = async (projectId: string, variantIndex: number) => {
    if (!host().sendFollowUpMessage) return;
    await host().sendFollowUpMessage({
      role: "user",
      content: [
        {
          type: "text",
          text: `The EDMG timeline now has variant ${variantIndex + 1} applied for project ${projectId}. Tell me the best next step inside Studio.`,
        },
      ],
    });
  };

  const expandWidget = async () => {
    if (!host().requestDisplayMode) return;
    await host().requestDisplayMode({ mode: "fullscreen" });
  };

  return (
    <div className="shell">
      {isPlanPreview(output) ? (
        <PlanPreviewView output={output} onApply={applyPlanVariant} onAsk={askForNotes} onExpand={expandWidget} />
      ) : isActionResult(output) ? (
        <ActionResultView output={output} onAskNext={askForNextStep} onExpand={expandWidget} />
      ) : (
        <FallbackView output={output} />
      )}
      <StatusBanner busy={busy} error={error} />
    </div>
  );
}
