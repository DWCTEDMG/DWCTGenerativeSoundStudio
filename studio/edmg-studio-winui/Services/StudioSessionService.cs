using EdmgStudio.Core.Models;
using Windows.Storage;

namespace EdmgStudio.WinUI.Services;

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
    private readonly ApplicationDataContainer? _settings;
    private StudioWorkflowContext _context;

    public StudioSessionService()
    {
        try
        {
            _settings = ApplicationData.Current.LocalSettings;
        }
        catch
        {
            _settings = null;
        }

        _context = new StudioWorkflowContext(
            ActiveProjectId: ReadString(ProjectKey),
            SelectedVariant: ReadInt(VariantKey),
            SelectedArtifactPath: ReadString(ArtifactKey),
            SelectedJobId: ReadString(JobKey),
            SelectedJobProjectId: ReadString(JobProjectKey),
            SourceAssetPath: ReadString(SourceAssetKey),
            TimelineFocusSeconds: ReadDouble(TimelineFocusKey),
            RenderContext: ReadString(RenderContextKey),
            LastWorkflowDestination: ReadString(LastDestinationKey)).Normalize();
    }

    public event EventHandler? Changed;

    public StudioWorkflowContext Context => _context;

    public string ActiveProjectId
    {
        get => _context.ActiveProjectId ?? string.Empty;
        set
        {
            bool changed = !string.Equals(_context.ActiveProjectId, value?.Trim(), StringComparison.Ordinal);
            SetContext(_context.WithActiveProject(value));
            if (changed)
            {
                SetReviewComparison([], null);
            }
        }
    }

    public int SelectedVariantIndex
    {
        get => _context.SelectedVariant;
        set => SetContext(_context with { SelectedVariant = value });
    }

    public string? SelectedArtifactPath => _context.SelectedArtifactPath;

    public IReadOnlyList<string> ReviewComparisonPaths =>
        (ReadString(ComparisonPathsKey) ?? string.Empty)
            .Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .Take(StudioReviewSelection.MaximumComparisonArtifacts)
            .ToArray();

    public string? ReviewComparisonReference => ReadString(ComparisonReferenceKey);

    public string? SelectedJobId => _context.SelectedJobId;

    public string? SelectedJobProjectId => _context.SelectedJobProjectId;

    public bool QueueAllProjects
    {
        get => _settings?.Values[QueueAllProjectsKey] is bool value && value;
        set
        {
            if (_settings is not null)
            {
                _settings.Values[QueueAllProjectsKey] = value;
            }
        }
    }

    public RenderQueueFilter QueueFilter
    {
        get => Enum.TryParse(ReadString(QueueFilterKey), out RenderQueueFilter value)
            ? value
            : RenderQueueFilter.All;
        set => PersistString(QueueFilterKey, value.ToString());
    }

    public string? SourceAssetPath => _context.SourceAssetPath;

    public double? TimelineFocusSeconds => _context.TimelineFocusSeconds;

    public string? RenderContext => _context.RenderContext;

    public string? LastWorkflowDestination => _context.LastWorkflowDestination;

    public void SetSelectedArtifact(string? artifactPath) =>
        SetContext(_context with { SelectedArtifactPath = artifactPath });

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

    public void SetSelectedJob(string? projectId, string? jobId) =>
        SetContext(_context.WithSelectedJob(projectId, jobId));

    public void SetSourceAsset(string? sourceAssetPath) =>
        SetContext(_context with { SourceAssetPath = sourceAssetPath });

    public void SetTimelineFocus(double? timelineFocusSeconds) =>
        SetContext(_context with { TimelineFocusSeconds = timelineFocusSeconds });

    public void SetRenderContext(string? renderContext) =>
        SetContext(_context with { RenderContext = renderContext });

    public void SetLastWorkflowDestination(string? destination) =>
        SetContext(_context with { LastWorkflowDestination = destination });

    private string? ReadString(string key) => _settings?.Values[key] as string;

    private int ReadInt(string key) => _settings?.Values[key] is int value ? value : 0;

    private double? ReadDouble(string key) => _settings?.Values[key] is double value ? value : null;

    private void SetContext(StudioWorkflowContext context)
    {
        StudioWorkflowContext normalized = context.Normalize();
        if (_context == normalized)
        {
            return;
        }

        _context = normalized;
        Persist();
        Changed?.Invoke(this, EventArgs.Empty);
    }

    private void Persist()
    {
        if (_settings is null)
        {
            return;
        }

        PersistString(ProjectKey, _context.ActiveProjectId);
        _settings.Values[VariantKey] = _context.SelectedVariant;
        PersistString(ArtifactKey, _context.SelectedArtifactPath);
        PersistString(JobKey, _context.SelectedJobId);
        PersistString(JobProjectKey, _context.SelectedJobProjectId);
        PersistString(SourceAssetKey, _context.SourceAssetPath);
        PersistDouble(TimelineFocusKey, _context.TimelineFocusSeconds);
        PersistString(RenderContextKey, _context.RenderContext);
        PersistString(LastDestinationKey, _context.LastWorkflowDestination);
    }

    private void PersistString(string key, string? value)
    {
        if (_settings is null)
        {
            return;
        }

        if (value is null)
        {
            _settings.Values.Remove(key);
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
            _settings!.Values.Remove(key);
        }
        else
        {
            _settings!.Values[key] = value.Value;
        }
    }
}
