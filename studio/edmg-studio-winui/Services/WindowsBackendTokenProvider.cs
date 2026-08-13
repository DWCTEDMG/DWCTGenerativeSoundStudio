using EdmgStudio.Core.Services;
using Windows.Security.Credentials;

namespace EdmgStudio.WinUI.Services;

public sealed class WindowsBackendTokenProvider : IBackendTokenProvider
{
    private const string VaultResource = "EDMG Studio Backend";
    private const string VaultUser = "BackendAuthToken";
    private readonly IBackendTokenProvider _fallback;

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

        try
        {
            var credential = new PasswordVault().Retrieve(VaultResource, VaultUser);
            credential.RetrievePassword();
            return string.IsNullOrWhiteSpace(credential.Password) ? null : credential.Password;
        }
        catch
        {
            return null;
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
