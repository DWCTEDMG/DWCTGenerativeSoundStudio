using EdmgStudio.Core.Services;
using EdmgStudio.WinUI.Graphics;

namespace EdmgStudio.WinUI.Services;

public sealed class AppServices : IAsyncDisposable
{
    private readonly object _previewSessionsSync = new();
    private readonly HashSet<PreviewRendererSession> _previewSessions = [];
    private bool _isDisposing;

    private AppServices(
        BackendConfiguration configuration,
        BackendSupervisor backendSupervisor,
        StudioApiClient apiClient,
        StudioSessionService session)
    {
        Configuration = configuration;
        BackendSupervisor = backendSupervisor;
        ApiClient = apiClient;
        Session = session;
    }

    public BackendConfiguration Configuration { get; }
    public BackendSupervisor BackendSupervisor { get; }
    public StudioApiClient ApiClient { get; }
    public StudioSessionService Session { get; }

    internal bool TryTrackPreviewSession(PreviewRendererSession session)
    {
        ArgumentNullException.ThrowIfNull(session);
        lock (_previewSessionsSync)
        {
            if (_isDisposing)
            {
                return false;
            }

            return _previewSessions.Add(session);
        }
    }

    internal void UntrackPreviewSession(PreviewRendererSession session)
    {
        lock (_previewSessionsSync)
        {
            _previewSessions.Remove(session);
        }
    }

    public static AppServices Create()
    {
        var configuration = BackendConfiguration.Load();
        var tokenProvider = new WindowsBackendTokenProvider(new EnvironmentBackendTokenProvider());
        var launchToken = tokenProvider.GetTokenAsync().AsTask().GetAwaiter().GetResult();
        if (!string.IsNullOrWhiteSpace(launchToken))
        {
            var managedEnvironment = new Dictionary<string, string>(configuration.ManagedEnvironment, StringComparer.OrdinalIgnoreCase)
            {
                ["EDMG_BACKEND_AUTH_TOKEN"] = launchToken
            };
            configuration = configuration with { ManagedEnvironment = managedEnvironment };
        }

        var supervisor = new BackendSupervisor(configuration);
        var apiClient = new StudioApiClient(supervisor, tokenProvider);
        return new AppServices(configuration, supervisor, apiClient, new StudioSessionService());
    }

    public async ValueTask DisposeAsync()
    {
        List<Exception>? failures = null;
        PreviewRendererSession[] previewSessions;
        lock (_previewSessionsSync)
        {
            if (_isDisposing)
            {
                return;
            }

            _isDisposing = true;
            previewSessions = [.. _previewSessions];
            _previewSessions.Clear();
        }

        foreach (PreviewRendererSession session in previewSessions)
        {
            try
            {
                await session.DisposeAsync();
            }
            catch (Exception exception)
            {
                (failures ??= []).Add(exception);
            }
        }

        try
        {
            await BackendSupervisor.DisposeAsync();
        }
        catch (Exception exception)
        {
            (failures ??= []).Add(exception);
        }

        try
        {
            ApiClient.Dispose();
        }
        catch (Exception exception)
        {
            (failures ??= []).Add(exception);
        }

        if (failures is not null)
        {
            throw new AggregateException("One or more application services failed to shut down cleanly.", failures);
        }
    }
}
