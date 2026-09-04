using EdmgStudio.Core.Services;
using Windows.Security.Credentials;

namespace EdmgStudio.WinUI.Services;

public sealed class WindowsBackendTokenProvider : IBackendTokenProvider
{
    private const string VaultResource = "EDMG Studio Backend";
    private const string VaultUser = "BackendAuthToken";
    private readonly IBackendTokenProvider _fallback;
    private readonly SemaphoreSlim _vaultGate = new(1, 1);

    private bool _vaultChecked;
    private string? _cachedVaultToken;

    public WindowsBackendTokenProvider(IBackendTokenProvider fallback)
    {
        _fallback = fallback;
    }

    public async ValueTask<string?> GetTokenAsync(CancellationToken cancellationToken = default)
    {
        var environmentToken = await _fallback.GetTokenAsync(cancellationToken);
        if (!string.IsNullOrWhiteSpace(environmentToken))
        {
            return environmentToken;
        }

        if (_vaultChecked)
        {
            return _cachedVaultToken;
        }

        await _vaultGate.WaitAsync(cancellationToken);
        try
        {
            if (_vaultChecked)
            {
                return _cachedVaultToken;
            }

            try
            {
                var credential = new PasswordVault().Retrieve(VaultResource, VaultUser);
                credential.RetrievePassword();
                _cachedVaultToken = string.IsNullOrWhiteSpace(credential.Password)
                    ? null
                    : credential.Password;
            }
            catch
            {
                // A missing credential is normal for a local backend that does not
                // require authentication. Cache that result so every HTTP request
                // does not repeatedly ask PasswordVault and trigger a first-chance
                // COMException in the Visual Studio debugger.
                _cachedVaultToken = null;
            }

            _vaultChecked = true;
            return _cachedVaultToken;
        }
        finally
        {
            _vaultGate.Release();
        }
    }

    public static void Save(string? token)
    {
        try
        {
            var vault = new PasswordVault();
            try
            {
                var existing = vault.Retrieve(VaultResource, VaultUser);
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
        catch (Exception exception)
        {
            throw new InvalidOperationException(
                "Windows Credential Locker could not save the backend token on this device.",
                exception);
        }
    }
}
