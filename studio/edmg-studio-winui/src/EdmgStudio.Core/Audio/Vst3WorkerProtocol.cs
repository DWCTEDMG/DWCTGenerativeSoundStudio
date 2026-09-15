using System.Diagnostics;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace EdmgStudio.Core.Audio;

public sealed record Vst3WorkerRequest(int ProtocolVersion, string RequestId, string Operation, string? InstanceId, float[]? Samples);
public sealed record Vst3WorkerResponse(int ProtocolVersion, string RequestId, bool Success, float[]? Samples, string? Diagnostic);

public static class Vst3WorkerProtocol
{
    public const int Version = 1;
    public const int MaximumMessageBytes = 1024 * 1024;
    private static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow
    };

    public static string Serialize(Vst3WorkerRequest request)
    {
        Validate(request);
        string json = JsonSerializer.Serialize(request, Options);
        if (Encoding.UTF8.GetByteCount(json) > MaximumMessageBytes) throw new InvalidDataException("VST3 worker request exceeds the protocol limit.");
        return json;
    }

    public static Vst3WorkerResponse ParseResponse(string json, string expectedRequestId)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(json);
        ArgumentException.ThrowIfNullOrWhiteSpace(expectedRequestId);
        if (Encoding.UTF8.GetByteCount(json) > MaximumMessageBytes) throw new InvalidDataException("VST3 worker response exceeds the protocol limit.");
        Vst3WorkerResponse response;
        try { response = JsonSerializer.Deserialize<Vst3WorkerResponse>(json, Options) ?? throw new JsonException(); }
        catch (JsonException exception) { throw new InvalidDataException("Malformed VST3 worker response.", exception); }
        if (response.ProtocolVersion != Version || !string.Equals(response.RequestId, expectedRequestId, StringComparison.Ordinal) ||
            response.Samples?.Any(sample => !float.IsFinite(sample)) == true)
            throw new InvalidDataException("VST3 worker response violates the protocol contract.");
        return response;
    }

    private static void Validate(Vst3WorkerRequest request)
    {
        ArgumentNullException.ThrowIfNull(request);
        if (request.ProtocolVersion != Version || string.IsNullOrWhiteSpace(request.RequestId) || string.IsNullOrWhiteSpace(request.Operation) ||
            request.Samples?.Any(sample => !float.IsFinite(sample)) == true)
            throw new InvalidDataException("VST3 worker request violates the protocol contract.");
    }
}

public sealed class Vst3WorkerProcessClient(string executablePath, IEnumerable<string>? arguments = null)
{
    private readonly string _executablePath = string.IsNullOrWhiteSpace(executablePath) ? throw new ArgumentException("Worker path is required.", nameof(executablePath)) : executablePath;
    private readonly string[] _arguments = arguments?.ToArray() ?? [];

    public async Task<Vst3WorkerResponse> SendAsync(Vst3WorkerRequest request, TimeSpan timeout, CancellationToken cancellationToken = default)
    {
        if (timeout <= TimeSpan.Zero) throw new ArgumentOutOfRangeException(nameof(timeout));
        var startInfo = new ProcessStartInfo(_executablePath) { UseShellExecute = false, CreateNoWindow = true, RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true };
        foreach (string argument in _arguments) startInfo.ArgumentList.Add(argument);
        using var process = new Process { StartInfo = startInfo };
        if (!process.Start()) throw new InvalidOperationException("The VST3 worker did not start.");
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        linked.CancelAfter(timeout);
        try
        {
            await process.StandardInput.WriteLineAsync(Vst3WorkerProtocol.Serialize(request).AsMemory(), linked.Token).ConfigureAwait(false);
            process.StandardInput.Close();
            string? response = await process.StandardOutput.ReadLineAsync(linked.Token).ConfigureAwait(false);
            await process.WaitForExitAsync(linked.Token).ConfigureAwait(false);
            string error = await process.StandardError.ReadToEndAsync(linked.Token).ConfigureAwait(false);
            if (process.ExitCode != 0) throw new InvalidOperationException($"VST3 worker exited with code {process.ExitCode}: {error.Trim()}");
            return Vst3WorkerProtocol.ParseResponse(response ?? throw new InvalidDataException("VST3 worker returned no response."), request.RequestId);
        }
        catch (OperationCanceledException)
        {
            try { if (!process.HasExited) process.Kill(entireProcessTree: true); } catch (InvalidOperationException) { }
            throw;
        }
    }
}