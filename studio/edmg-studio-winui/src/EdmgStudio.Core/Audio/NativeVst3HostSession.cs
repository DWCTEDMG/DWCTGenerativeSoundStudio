using System.Buffers.Binary;
using System.Collections.Concurrent;
using System.Collections.Immutable;
using System.Diagnostics;
using System.IO.Pipes;
using System.Text;

namespace EdmgStudio.Core.Audio;

public sealed class NativeVst3HostSession : IVst3HostSession
{
    private readonly string _hostPath;
    private readonly TimeSpan _controlTimeout;
    private readonly TimeSpan _processTimeout;
    private readonly ConcurrentDictionary<string, NativeVst3Worker> _workers = new(StringComparer.Ordinal);

    public NativeVst3HostSession(string hostPath, TimeSpan? controlTimeout = null, TimeSpan? processTimeout = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(hostPath);
        _hostPath = Path.GetFullPath(hostPath);
        _controlTimeout = controlTimeout ?? TimeSpan.FromSeconds(10);
        _processTimeout = processTimeout ?? TimeSpan.FromMilliseconds(250);
        Capabilities = File.Exists(_hostPath)
            ? Vst3HostCapabilities.NativeWorker("Native crash-isolated VST3 worker is available.")
            : Vst3HostCapabilities.Unavailable($"Native VST3 host was not found at {_hostPath}.");
    }

    public Vst3HostCapabilities Capabilities { get; }

    public async ValueTask<Vst3InstanceStatus> CreateInstanceAsync(Vst3InstanceRequest request, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(request);
        if (!File.Exists(_hostPath)) return new(request.InstanceId, false, 0, Capabilities.Diagnostic, Health: Vst3WorkerHealth.Failed);
        if (request.MaximumFrames is < 1 or > 16384) throw new ArgumentOutOfRangeException(nameof(request), "MaximumFrames must be between 1 and 16384.");
        var worker = new NativeVst3Worker(_hostPath, request, _controlTimeout, _processTimeout);
        if (!_workers.TryAdd(request.InstanceId, worker)) throw new InvalidOperationException($"VST3 instance '{request.InstanceId}' already exists.");
        try
        {
            return await worker.StartAsync(cancellationToken).ConfigureAwait(false);
        }
        catch
        {
            _workers.TryRemove(request.InstanceId, out _);
            await worker.DisposeAsync().ConfigureAwait(false);
            throw;
        }
    }

    public async ValueTask<Vst3InstanceStatus> SetStateAsync(string instanceId, ReadOnlyMemory<byte> state, CancellationToken cancellationToken = default)
    {
        NativeVst3Worker worker = GetWorker(instanceId);
        await worker.SendControlAsync(WorkerOperation.SetState, state, cancellationToken).ConfigureAwait(false);
        return worker.Status;
    }

    public async ValueTask<ReadOnlyMemory<byte>> GetStateAsync(string instanceId, CancellationToken cancellationToken = default) =>
        await GetWorker(instanceId).SendControlAsync(WorkerOperation.GetState, ReadOnlyMemory<byte>.Empty, cancellationToken).ConfigureAwait(false);

    public async ValueTask<Vst3InstanceStatus> SetParameterAsync(string instanceId, uint parameterId, double normalizedValue, CancellationToken cancellationToken = default)
    {
        if (!double.IsFinite(normalizedValue) || normalizedValue is < 0 or > 1) throw new ArgumentOutOfRangeException(nameof(normalizedValue));
        byte[] payload = new byte[12];
        BinaryPrimitives.WriteUInt32LittleEndian(payload, parameterId);
        BinaryPrimitives.WriteInt64LittleEndian(payload.AsSpan(4), BitConverter.DoubleToInt64Bits(normalizedValue));
        NativeVst3Worker worker = GetWorker(instanceId);
        await worker.SendControlAsync(WorkerOperation.SetParameter, payload, cancellationToken).ConfigureAwait(false);
        worker.UpdateParameter(parameterId, normalizedValue);
        return worker.Status;
    }

    public async ValueTask QueueMidiEventsAsync(string instanceId, IReadOnlyList<Vst3MidiEvent> events, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(events);
        if (events.Count > 4096) throw new ArgumentOutOfRangeException(nameof(events), "At most 4096 MIDI events may be queued per process block.");
        byte[] payload = new byte[checked(4 + events.Count * 20)];
        BinaryPrimitives.WriteUInt32LittleEndian(payload, (uint)events.Count);
        for (int index = 0; index < events.Count; index++)
        {
            Vst3MidiEvent midiEvent = events[index];
            if (midiEvent.Channel is < 0 or > 15 || midiEvent.Note is < 0 or > 127 || !double.IsFinite(midiEvent.Velocity) || midiEvent.Velocity is < 0 or > 1 || midiEvent.SampleOffset < 0)
                throw new ArgumentOutOfRangeException(nameof(events), $"MIDI event {index} is outside the supported VST3 range.");
            Span<byte> eventPayload = payload.AsSpan(4 + index * 20, 20);
            BinaryPrimitives.WriteUInt32LittleEndian(eventPayload, (uint)midiEvent.Kind);
            BinaryPrimitives.WriteInt32LittleEndian(eventPayload[4..], midiEvent.Channel);
            BinaryPrimitives.WriteInt32LittleEndian(eventPayload[8..], midiEvent.Note);
            BinaryPrimitives.WriteInt32LittleEndian(eventPayload[12..], BitConverter.SingleToInt32Bits((float)midiEvent.Velocity));
            BinaryPrimitives.WriteInt32LittleEndian(eventPayload[16..], midiEvent.SampleOffset);
        }
        await GetWorker(instanceId).SendControlAsync(WorkerOperation.QueueMidiEvents, payload, cancellationToken).ConfigureAwait(false);
    }

    public bool TryGetProcessor(string instanceId, out IVst3InsertProcessor? processor)
    {
        bool found = _workers.TryGetValue(instanceId, out NativeVst3Worker? worker);
        processor = worker;
        return found;
    }

    public async ValueTask RemoveInstanceAsync(string instanceId, CancellationToken cancellationToken = default)
    {
        if (_workers.TryRemove(instanceId, out NativeVst3Worker? worker))
            await worker.DisposeAsync().ConfigureAwait(false);
    }

    internal ValueTask SimulateWorkerFailureAsync(string instanceId, bool timeout, CancellationToken cancellationToken = default) =>
        GetWorker(instanceId).SimulateFailureAsync(timeout ? WorkerOperation.Hang : WorkerOperation.Crash, cancellationToken);

    public async ValueTask DisposeAsync()
    {
        NativeVst3Worker[] workers = _workers.Values.ToArray();
        _workers.Clear();
        foreach (NativeVst3Worker worker in workers) await worker.DisposeAsync().ConfigureAwait(false);
    }

    private NativeVst3Worker GetWorker(string instanceId) => _workers.TryGetValue(instanceId, out NativeVst3Worker? worker)
        ? worker : throw new KeyNotFoundException($"VST3 instance '{instanceId}' does not exist.");

    private enum WorkerOperation : uint { Ping = 1, Process = 2, SetParameter = 3, GetState = 4, SetState = 5, Shutdown = 6, Crash = 7, Hang = 8, QueueMidiEvents = 9 }

    private sealed class NativeVst3Worker : IVst3InsertProcessor, IAsyncDisposable
    {
        private const uint Magic = 0x33475456;
        private const uint Version = 1;
        private const int RequestHeaderBytes = 20;
        private const int ResponseHeaderBytes = 24;
        private const int MaximumPayloadBytes = 16 * 1024 * 1024;
        private readonly string _hostPath;
        private readonly Vst3InstanceRequest _request;
        private readonly TimeSpan _controlTimeout;
        private readonly TimeSpan _processTimeout;
        private readonly SemaphoreSlim _gate = new(1, 1);
        private readonly byte[] _processRequest;
        private readonly byte[] _processResponse;
        private Process? _process;
        private NamedPipeServerStream? _requestPipe;
        private NamedPipeServerStream? _responsePipe;
        private int _requestId;
        private bool _disposed;
        private ImmutableArray<Vst3ParameterDescriptor> _parameters = [];

        public NativeVst3Worker(string hostPath, Vst3InstanceRequest request, TimeSpan controlTimeout, TimeSpan processTimeout)
        {
            _hostPath = hostPath;
            _request = request;
            _controlTimeout = controlTimeout;
            _processTimeout = processTimeout;
            _processRequest = new byte[checked(4 + request.MaximumFrames * 2 * sizeof(float))];
            _processResponse = new byte[_processRequest.Length];
        }

        public string InstanceId => _request.InstanceId;
        public string ModulePath => _request.ModulePath;
        public string PluginId => _request.PluginId;
        public int SampleRate => _request.SampleRate;
        public int MaximumFrames => _request.MaximumFrames;
        public int ReportedLatencySamples { get; private set; }
        public int AudioInputs { get; private set; }
        public int AudioOutputs { get; private set; }
        public Vst3WorkerHealth Health { get; private set; } = Vst3WorkerHealth.Starting;
        public string? Diagnostic { get; private set; }
        public Vst3InstanceStatus Status => new(InstanceId, Health == Vst3WorkerHealth.Ready, ReportedLatencySamples,
            Diagnostic, AudioInputs, AudioOutputs, _parameters, Health);

        public async ValueTask<Vst3InstanceStatus> StartAsync(CancellationToken cancellationToken)
        {
            string suffix = $"edmg-vst3-{Environment.ProcessId}-{Guid.NewGuid():N}";
            _requestPipe = new NamedPipeServerStream(suffix + "-request", PipeDirection.Out, 1, PipeTransmissionMode.Byte, PipeOptions.Asynchronous);
            _responsePipe = new NamedPipeServerStream(suffix + "-response", PipeDirection.In, 1, PipeTransmissionMode.Byte, PipeOptions.Asynchronous);
            var startInfo = new ProcessStartInfo(_hostPath) { UseShellExecute = false, CreateNoWindow = true, RedirectStandardError = true };
            startInfo.ArgumentList.Add("--worker");
            startInfo.ArgumentList.Add("--module"); startInfo.ArgumentList.Add(_request.ModulePath);
            startInfo.ArgumentList.Add("--plugin-id"); startInfo.ArgumentList.Add(_request.PluginId);
            startInfo.ArgumentList.Add("--sample-rate"); startInfo.ArgumentList.Add(_request.SampleRate.ToString(System.Globalization.CultureInfo.InvariantCulture));
            startInfo.ArgumentList.Add("--frames"); startInfo.ArgumentList.Add(_request.MaximumFrames.ToString(System.Globalization.CultureInfo.InvariantCulture));
            startInfo.ArgumentList.Add("--request-pipe"); startInfo.ArgumentList.Add($@"\\.\pipe\{suffix}-request");
            startInfo.ArgumentList.Add("--response-pipe"); startInfo.ArgumentList.Add($@"\\.\pipe\{suffix}-response");
            _process = Process.Start(startInfo) ?? throw new InvalidOperationException("Native VST3 worker could not be started.");
            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            timeout.CancelAfter(_controlTimeout);
            await Task.WhenAll(_requestPipe.WaitForConnectionAsync(timeout.Token), _responsePipe.WaitForConnectionAsync(timeout.Token)).ConfigureAwait(false);
            WorkerResponse response = await SendAsync(WorkerOperation.Ping, ReadOnlyMemory<byte>.Empty, _controlTimeout, timeout.Token).ConfigureAwait(false);
            ParseMetadata(response.Payload.Span);
            Diagnostic = response.Diagnostic;
            Health = Vst3WorkerHealth.Ready;
            return Status;
        }

        public async ValueTask<ReadOnlyMemory<byte>> SendControlAsync(WorkerOperation operation, ReadOnlyMemory<byte> payload, CancellationToken cancellationToken)
        {
            try
            {
                WorkerResponse response = await SendAsync(operation, payload, _controlTimeout, cancellationToken).ConfigureAwait(false);
                return response.Payload;
            }
            catch (TimeoutException exception)
            {
                Fail(Vst3WorkerHealth.TimedOut, exception.Message);
                throw;
            }
        }

        public bool TryProcessInPlace(Span<float> interleavedStereo, int frames)
        {
            if (Health != Vst3WorkerHealth.Ready || frames < 0 || frames > _request.MaximumFrames || interleavedStereo.Length < frames * 2) return false;
            BinaryPrimitives.WriteUInt32LittleEndian(_processRequest, (uint)frames);
            interleavedStereo[..(frames * 2)].CopyTo(System.Runtime.InteropServices.MemoryMarshal.Cast<byte, float>(_processRequest.AsSpan(4)));
            try
            {
                WorkerResponse response = SendAsync(WorkerOperation.Process, _processRequest.AsMemory(0, 4 + frames * 8), _processTimeout, CancellationToken.None).AsTask().GetAwaiter().GetResult();
                if (response.Payload.Length != 4 + frames * 8 || BinaryPrimitives.ReadUInt32LittleEndian(response.Payload.Span) != frames) throw new InvalidDataException("VST3 worker returned an invalid audio block.");
                System.Runtime.InteropServices.MemoryMarshal.Cast<byte, float>(response.Payload.Span[4..]).CopyTo(interleavedStereo);
                return true;
            }
            catch (TimeoutException exception) { Fail(Vst3WorkerHealth.TimedOut, exception.Message); return false; }
            catch (Exception exception) { Fail(_process?.HasExited == true ? Vst3WorkerHealth.Exited : Vst3WorkerHealth.Failed, exception.Message); return false; }
        }

        public void Reset() { }
        public void Dispose() => DisposeAsync().AsTask().GetAwaiter().GetResult();

        public async ValueTask DisposeAsync()
        {
            if (_disposed) return;
            _disposed = true;
            if (Health == Vst3WorkerHealth.Ready)
            {
                try { await SendAsync(WorkerOperation.Shutdown, ReadOnlyMemory<byte>.Empty, _controlTimeout, CancellationToken.None).ConfigureAwait(false); }
                catch { }
            }
            if (_process is { HasExited: false })
            {
                _process.Kill(entireProcessTree: true);
                await _process.WaitForExitAsync().ConfigureAwait(false);
            }
            _requestPipe?.Dispose(); _responsePipe?.Dispose(); _process?.Dispose(); _gate.Dispose();
            Health = Vst3WorkerHealth.Disposed;
        }

        public void UpdateParameter(uint parameterId, double value)
        {
            for (int index = 0; index < _parameters.Length; index++)
            {
                if (_parameters[index].Id != parameterId) continue;
                _parameters = _parameters.SetItem(index, _parameters[index] with { NormalizedValue = value });
                break;
            }
        }

        public async ValueTask SimulateFailureAsync(WorkerOperation operation, CancellationToken cancellationToken)
        {
            if (operation is not (WorkerOperation.Crash or WorkerOperation.Hang)) throw new ArgumentOutOfRangeException(nameof(operation));
            try
            {
                await SendAsync(operation, ReadOnlyMemory<byte>.Empty, _processTimeout, cancellationToken).ConfigureAwait(false);
                throw new InvalidOperationException("Native VST3 worker did not execute the requested failure probe.");
            }
            catch (TimeoutException exception)
            {
                Fail(operation == WorkerOperation.Crash ? Vst3WorkerHealth.Exited : Vst3WorkerHealth.TimedOut, exception.Message);
            }
            catch (Exception exception)
            {
                Fail(_process?.HasExited == true ? Vst3WorkerHealth.Exited : Vst3WorkerHealth.Failed, exception.Message);
            }
        }

        private async ValueTask<WorkerResponse> SendAsync(
            WorkerOperation operation,
            ReadOnlyMemory<byte> payload,
            TimeSpan timeout,
            CancellationToken cancellationToken)
        {
            if (payload.Length > MaximumPayloadBytes) throw new InvalidDataException("VST3 worker payload exceeds the protocol limit.");
            await _gate.WaitAsync(cancellationToken).ConfigureAwait(false);
            try
            {
                if (_process is null || _requestPipe is null || _responsePipe is null || _process.HasExited) throw new IOException("Native VST3 worker is not running.");
                using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
                deadline.CancelAfter(timeout);
                int requestId = Interlocked.Increment(ref _requestId);
                byte[] header = new byte[RequestHeaderBytes];
                BinaryPrimitives.WriteUInt32LittleEndian(header, Magic);
                BinaryPrimitives.WriteUInt32LittleEndian(header.AsSpan(4), Version);
                BinaryPrimitives.WriteUInt32LittleEndian(header.AsSpan(8), (uint)operation);
                BinaryPrimitives.WriteUInt32LittleEndian(header.AsSpan(12), (uint)requestId);
                BinaryPrimitives.WriteUInt32LittleEndian(header.AsSpan(16), (uint)payload.Length);
                await _requestPipe.WriteAsync(header, deadline.Token).ConfigureAwait(false);
                if (!payload.IsEmpty) await _requestPipe.WriteAsync(payload, deadline.Token).ConfigureAwait(false);
                await _requestPipe.FlushAsync(deadline.Token).ConfigureAwait(false);
                byte[] responseHeader = new byte[ResponseHeaderBytes];
                await _responsePipe.ReadExactlyAsync(responseHeader, deadline.Token).ConfigureAwait(false);
                uint payloadBytes = BinaryPrimitives.ReadUInt32LittleEndian(responseHeader.AsSpan(16));
                uint diagnosticBytes = BinaryPrimitives.ReadUInt32LittleEndian(responseHeader.AsSpan(20));
                if (BinaryPrimitives.ReadUInt32LittleEndian(responseHeader) != Magic || BinaryPrimitives.ReadUInt32LittleEndian(responseHeader.AsSpan(4)) != Version ||
                    BinaryPrimitives.ReadUInt32LittleEndian(responseHeader.AsSpan(12)) != (uint)requestId || payloadBytes > MaximumPayloadBytes || diagnosticBytes > 65536)
                    throw new InvalidDataException("Native VST3 worker returned an invalid response header.");
                byte[] responsePayload = new byte[payloadBytes];
                if (payloadBytes > 0) await _responsePipe.ReadExactlyAsync(responsePayload, deadline.Token).ConfigureAwait(false);
                byte[] diagnosticPayload = new byte[diagnosticBytes];
                if (diagnosticBytes > 0) await _responsePipe.ReadExactlyAsync(diagnosticPayload, deadline.Token).ConfigureAwait(false);
                string diagnostic = Encoding.UTF8.GetString(diagnosticPayload);
                if (BinaryPrimitives.ReadUInt32LittleEndian(responseHeader.AsSpan(8)) != 0) throw new InvalidOperationException(diagnostic);
                return new(responsePayload, diagnostic);
            }
            catch (OperationCanceledException exception) when (!cancellationToken.IsCancellationRequested)
            {
                throw new TimeoutException("Native VST3 worker request timed out.", exception);
            }
            finally { _gate.Release(); }
        }

        private void ParseMetadata(ReadOnlySpan<byte> payload)
        {
            byte[] metadata = payload.ToArray();
            int offset = 0;
            uint ReadUInt32() { if (offset + 4 > metadata.Length) throw new InvalidDataException("Worker metadata is truncated."); uint value = BinaryPrimitives.ReadUInt32LittleEndian(metadata.AsSpan(offset)); offset += 4; return value; }
            double ReadDouble() { if (offset + 8 > metadata.Length) throw new InvalidDataException("Worker metadata is truncated."); double value = BitConverter.Int64BitsToDouble(BinaryPrimitives.ReadInt64LittleEndian(metadata.AsSpan(offset))); offset += 8; return value; }
            AudioInputs = checked((int)ReadUInt32()); AudioOutputs = checked((int)ReadUInt32()); ReportedLatencySamples = checked((int)ReadUInt32());
            int count = checked((int)ReadUInt32());
            var parameters = ImmutableArray.CreateBuilder<Vst3ParameterDescriptor>(count);
            for (int index = 0; index < count; index++)
            {
                uint id = ReadUInt32(); double normalized = ReadDouble(); int nameBytes = checked((int)ReadUInt32());
                if (nameBytes < 0 || offset + nameBytes > metadata.Length) throw new InvalidDataException($"Worker parameter metadata is truncated at parameter {index}: offset={offset}, nameBytes={nameBytes}, payloadBytes={metadata.Length}.");
                string name = Encoding.UTF8.GetString(metadata.AsSpan(offset, nameBytes)); offset += nameBytes;
                double defaultValue = ReadDouble();
                bool isReadOnly = ReadUInt32() != 0;
                int unitsBytes = checked((int)ReadUInt32());
                if (unitsBytes < 0 || offset + unitsBytes > metadata.Length) throw new InvalidDataException("Worker parameter units are truncated.");
                string units = Encoding.UTF8.GetString(metadata.AsSpan(offset, unitsBytes)); offset += unitsBytes;
                int displayBytes = checked((int)ReadUInt32());
                if (displayBytes < 0 || offset + displayBytes > metadata.Length) throw new InvalidDataException("Worker parameter display value is truncated.");
                string display = Encoding.UTF8.GetString(metadata.AsSpan(offset, displayBytes)); offset += displayBytes;
                parameters.Add(new(id, name, normalized, defaultValue, isReadOnly, units, display));
            }
            if (offset != metadata.Length) throw new InvalidDataException("Worker metadata contains trailing bytes.");
            _parameters = parameters.MoveToImmutable();
        }

        private void Fail(Vst3WorkerHealth health, string diagnostic)
        {
            Health = health; Diagnostic = diagnostic;
            if (_process is { HasExited: false }) _process.Kill(entireProcessTree: true);
        }

        private sealed record WorkerResponse(ReadOnlyMemory<byte> Payload, string Diagnostic);
    }
}
