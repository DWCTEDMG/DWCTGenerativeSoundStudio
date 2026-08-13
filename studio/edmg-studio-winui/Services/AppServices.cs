using EdmgStudio.Core.Services;

namespace EdmgStudio.WinUI.Services;

public sealed class AppServices : IAsyncDisposable
{
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
        ApiClient.Dispose();
        await BackendSupervisor.DisposeAsync();
    }
}
