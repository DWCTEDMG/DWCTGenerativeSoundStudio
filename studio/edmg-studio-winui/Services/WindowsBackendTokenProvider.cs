using EdmgStudio.Core.Services;
using Windows.Security.Credentials;

namespace EdmgStudio.WinUI.Services;

public sealed class WindowsBackendTokenProvider : IBackendTokenProvider
{
  private const string VaultResource = "EDMG Studio Backend";
  private const string VaultUser = "BackendAuthToken";

  private static readonly ProcessWideTokenCacheCoordinator s_cacheCoordinator = new();
  private static Func<IWindowsBackendTokenStore> s_storeFactory = static () => new PasswordVaultBackendTokenStore();

  private readonly IBackendTokenProvider _fallback;
  private readonly SemaphoreSlim _vaultGate = new(1, 1);

  private readonly TokenCacheEntry _vaultTokenCache = s_cacheCoordinator.CreateEntry();

  public WindowsBackendTokenProvider(IBackendTokenProvider fallback)
  {
    _fallback = fallback;
  }

  public async ValueTask<string?> GetTokenAsync(CancellationToken cancellationToken = default)
  {
    string? environmentToken = await _fallback.GetTokenAsync(cancellationToken);
    if (!string.IsNullOrWhiteSpace(environmentToken))
    {
      return environmentToken;
    }

    if (_vaultTokenCache.TryGet(out string? cachedVaultToken))
    {
      return cachedVaultToken;
    }

    await _vaultGate.WaitAsync(cancellationToken);
    try
    {
      while (true)
      {
        cancellationToken.ThrowIfCancellationRequested();
        if (_vaultTokenCache.TryGet(out cachedVaultToken))
        {
          return cachedVaultToken;
        }

        long version = s_cacheCoordinator.CurrentVersion;
        try
        {
          cachedVaultToken = ResolveStore().ReadToken();
        }
        catch
        {
          // Missing credentials are normal; cache absence until Save/clear.
          cachedVaultToken = null;
        }
        if (_vaultTokenCache.StoreIfCurrent(cachedVaultToken, version))
        {
          return cachedVaultToken;
        }
      }
    }
    finally
    {
      _ = _vaultGate.Release();
    }
  }
  public static void Save(string? token)
  {
    try
    {
      ResolveStore().WriteToken(string.IsNullOrWhiteSpace(token) ? null : token.Trim());
      s_cacheCoordinator.Invalidate();
    }
    catch (Exception exception)
    {
      throw new InvalidOperationException(
          "Windows Credential Locker could not save the backend token on this device.",
          exception);
    }
  }

  internal static IDisposable OverrideStoreFactoryForTesting(Func<IWindowsBackendTokenStore> storeFactory)
  {
    ArgumentNullException.ThrowIfNull(storeFactory);

    Func<IWindowsBackendTokenStore> previous = Interlocked.Exchange(ref s_storeFactory, storeFactory);
    s_cacheCoordinator.Invalidate();
    return new DelegateDisposable(() =>
    {
      _ = Interlocked.Exchange(ref s_storeFactory, previous);
      s_cacheCoordinator.Invalidate();
    });
  }

  private static IWindowsBackendTokenStore ResolveStore()
  {
    return Volatile.Read(ref s_storeFactory)();
  }

  private sealed class PasswordVaultBackendTokenStore : IWindowsBackendTokenStore
  {
    public string? ReadToken()
    {
      PasswordCredential credential = new PasswordVault().Retrieve(VaultResource, VaultUser);
      credential.RetrievePassword();
      return string.IsNullOrWhiteSpace(credential.Password)
          ? null
          : credential.Password;
    }

    public void WriteToken(string? token)
    {
      PasswordVault vault = new();
      try
      {
        PasswordCredential existing = vault.Retrieve(VaultResource, VaultUser);
        vault.Remove(existing);
      }
      catch
      {
      }

      if (!string.IsNullOrWhiteSpace(token))
      {
        vault.Add(new PasswordCredential(VaultResource, VaultUser, token.Trim()));
      }
    }
  }

  private sealed class DelegateDisposable(Action dispose) : IDisposable
  {
    private int _disposed;

    public void Dispose()
    {
      if (Interlocked.Exchange(ref _disposed, 1) == 0)
      {
        dispose();
      }
    }
  }
}

internal interface IWindowsBackendTokenStore
{
  string? ReadToken();

  void WriteToken(string? token);
}
