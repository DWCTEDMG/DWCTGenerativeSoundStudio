using EdmgStudio.Core.Models;
using Windows.Storage;

namespace EdmgStudio.WinUI.Services;

public sealed class ProjectContentChangedEventArgs(string projectId) : EventArgs
{
  public string ProjectId { get; } = projectId;
}

public sealed class StudioSessionService
{
  private const string ProjectKey = "StudioSession.ActiveProjectId";
  private const string VariantKey = "StudioSession.SelectedVariant";
  private const string ArtifactKey = "StudioSession.SelectedArtifactPath";
  private const string ComparisonPathsKey = "StudioSession.ReviewComparisonPaths";
  private const string ComparisonReferenceKey = "StudioSession.ReviewComparisonReference";
  private const string JobKey = "StudioSession.SelectedJobId";
  private const string JobProjectKey = "StudioSession.SelectedJobProjectId";
  private const string QueueAllProjectsKey = "StudioSession.QueueAllProjects";
  private const string QueueFilterKey = "StudioSession.QueueFilter";
  private const string SourceAssetKey = "StudioSession.SourceAssetPath";
  private const string TimelineFocusKey = "StudioSession.TimelineFocusSeconds";
  private const string RenderContextKey = "StudioSession.RenderContext";
  private const string LastDestinationKey = "StudioSession.LastWorkflowDestination";
  private const string TimelineSelectionStartKey = "StudioSession.TimelineSelectionStartSample";
  private const string TimelineSelectionEndKey = "StudioSession.TimelineSelectionEndSample";
  private const string ContextRevisionKey = "StudioSession.ContextRevision";
  private readonly ApplicationDataContainer? _settings;

  public StudioSessionService()
  {
    if (WindowsPackageIdentity.IsPackaged)
    {
      try
      {
        _settings = ApplicationData.Current.LocalSettings;
      }
      catch
      {
        _settings = null;
      }
    }

    Context = new StudioWorkflowContext(
        ActiveProjectId: ReadString(ProjectKey),
        SelectedVariant: ReadInt(VariantKey),
        SelectedArtifactPath: ReadString(ArtifactKey),
        SelectedJobId: ReadString(JobKey),
        SelectedJobProjectId: ReadString(JobProjectKey),
        SourceAssetPath: ReadString(SourceAssetKey),
        TimelineFocusSeconds: ReadDouble(TimelineFocusKey),
        RenderContext: ReadString(RenderContextKey),
        LastWorkflowDestination: ReadString(LastDestinationKey),
        TimelineSelectionStartSample: ReadLong(TimelineSelectionStartKey),
        TimelineSelectionEndSample: ReadLong(TimelineSelectionEndKey),
        ContextRevision: ReadLong(ContextRevisionKey) ?? 0).Normalize();
  }

  public event EventHandler? Changed;
  public event EventHandler<ProjectContentChangedEventArgs>? ProjectContentChanged;

  public StudioWorkflowContext Context { get; private set; }

  public string ActiveProjectId
  {
    get => Context.ActiveProjectId ?? string.Empty;
    set
    {
      bool changed = !string.Equals(Context.ActiveProjectId, value?.Trim(), StringComparison.Ordinal);
      SetContext(Context.WithActiveProject(value));
      if (changed)
      {
        SetReviewComparison([], null);
      }
    }
  }

  public int SelectedVariantIndex
  {
    get => Context.SelectedVariant;
    set => SetContext(Context with { SelectedVariant = value });
  }

  public string? SelectedArtifactPath => Context.SelectedArtifactPath;

  public IReadOnlyList<string> ReviewComparisonPaths =>
      (ReadString(ComparisonPathsKey) ?? string.Empty)
          .Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
          .Distinct(StringComparer.OrdinalIgnoreCase)
          .Take(StudioReviewSelection.MaximumComparisonArtifacts)
          .ToArray();

  public string? ReviewComparisonReference => ReadString(ComparisonReferenceKey);

  public string? SelectedJobId => Context.SelectedJobId;

  public string? SelectedJobProjectId => Context.SelectedJobProjectId;

  public bool QueueAllProjects
  {
    get => _settings?.Values[QueueAllProjectsKey] is bool value && value; set => _settings?.Values[QueueAllProjectsKey] = value;
  }

  public RenderQueueFilter QueueFilter
  {
    get => Enum.TryParse(ReadString(QueueFilterKey), out RenderQueueFilter value)
        ? value
        : RenderQueueFilter.All;
    set => PersistString(QueueFilterKey, value.ToString());
  }

  public string? SourceAssetPath => Context.SourceAssetPath;

  public double? TimelineFocusSeconds => Context.TimelineFocusSeconds;

  public string? RenderContext => Context.RenderContext;

  public string? LastWorkflowDestination => Context.LastWorkflowDestination;

  public long? TimelineSelectionStartSample => Context.TimelineSelectionStartSample;

  public long? TimelineSelectionEndSample => Context.TimelineSelectionEndSample;

  public long ContextRevision => Context.ContextRevision;

  public void SetSelectedArtifact(string? artifactPath)
  {
    SetContext(Context with { SelectedArtifactPath = artifactPath });
  }

  public void SetReviewComparison(IEnumerable<string>? paths, string? referencePath)
  {
    string[] normalized = (paths ?? [])
        .Where(path => !string.IsNullOrWhiteSpace(path))
        .Select(path => path.Trim())
        .Distinct(StringComparer.OrdinalIgnoreCase)
        .Take(StudioReviewSelection.MaximumComparisonArtifacts)
        .ToArray();
    string? reference = StudioReviewComparison.KeepReference(referencePath, normalized);
    PersistString(ComparisonPathsKey, normalized.Length == 0 ? null : string.Join('\n', normalized));
    PersistString(ComparisonReferenceKey, reference);
    Changed?.Invoke(this, EventArgs.Empty);
  }

  public void SetSelectedJob(string? projectId, string? jobId)
  {
    SetContext(Context.WithSelectedJob(projectId, jobId));
  }

  public void SetSourceAsset(string? sourceAssetPath)
  {
    SetContext(Context with { SourceAssetPath = sourceAssetPath });
  }

  public void SetTimelineFocus(double? timelineFocusSeconds)
  {
    SetContext(Context with { TimelineFocusSeconds = timelineFocusSeconds });
  }

  public void SetTimelineSelection(long? startSample, long? endSample, long contextRevision)
  {
    SetContext(Context.WithTimelineSelection(startSample, endSample, contextRevision));
  }

  public void SetRenderContext(string? renderContext)
  {
    SetContext(Context with { RenderContext = renderContext });
  }

  public void SetLastWorkflowDestination(string? destination)
  {
    SetContext(Context with { LastWorkflowDestination = destination });
  }

  public void NotifyProjectContentChanged(string projectId)
  {
    ProjectContentChanged?.Invoke(this, new ProjectContentChangedEventArgs(projectId));
  }

  private string? ReadString(string key)
  {
    return _settings?.Values[key] as string;
  }

  private int ReadInt(string key)
  {
    return _settings?.Values[key] is int value ? value : 0;
  }

  private double? ReadDouble(string key)
  {
    return _settings?.Values[key] is double value ? value : null;
  }

  private long? ReadLong(string key)
  {
    return _settings?.Values[key] is long value ? value : null;
  }

  private void SetContext(StudioWorkflowContext context)
  {
    StudioWorkflowContext normalized = context.Normalize();
    if (Context == normalized)
    {
      return;
    }

    Context = normalized;
    Persist();
    Changed?.Invoke(this, EventArgs.Empty);
  }

  private void Persist()
  {
    if (_settings is null)
    {
      return;
    }

    PersistString(ProjectKey, Context.ActiveProjectId);
    _settings.Values[VariantKey] = Context.SelectedVariant;
    PersistString(ArtifactKey, Context.SelectedArtifactPath);
    PersistString(JobKey, Context.SelectedJobId);
    PersistString(JobProjectKey, Context.SelectedJobProjectId);
    PersistString(SourceAssetKey, Context.SourceAssetPath);
    PersistDouble(TimelineFocusKey, Context.TimelineFocusSeconds);
    PersistString(RenderContextKey, Context.RenderContext);
    PersistString(LastDestinationKey, Context.LastWorkflowDestination);
    PersistLong(TimelineSelectionStartKey, Context.TimelineSelectionStartSample);
    PersistLong(TimelineSelectionEndKey, Context.TimelineSelectionEndSample);
    PersistLong(ContextRevisionKey, Context.ContextRevision);
  }

  private void PersistString(string key, string? value)
  {
    if (_settings is null)
    {
      return;
    }

    if (value is null)
    {
      _ = _settings.Values.Remove(key);
    }
    else
    {
      _settings.Values[key] = value;
    }
  }

  private void PersistDouble(string key, double? value)
  {
    if (value is null)
    {
      _ = _settings!.Values.Remove(key);
    }
    else
    {
      _settings!.Values[key] = value.Value;
    }
  }

  private void PersistLong(string key, long? value)
  {
    if (value is null)
    {
      _ = _settings!.Values.Remove(key);
    }
    else
    {
      _settings!.Values[key] = value.Value;
    }
  }
}
